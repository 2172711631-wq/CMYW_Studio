/**
 * 最小 ZIP 写入器 —— 3MF 本质就是一个带固定目录结构的 ZIP。
 * Minimal ZIP writer; a 3MF package is a ZIP with a fixed layout.
 *
 * 用浏览器原生 CompressionStream('deflate-raw') 压缩，省掉一个第三方依赖。
 * 老浏览器没有这个 API 时自动退回「存储」模式（不压缩），文件更大但完全合法，
 * Bambu Studio 一样能打开。
 */

const CRC_TABLE: Uint32Array = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

export function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

/** 浏览器是否支持原生 raw deflate。 */
export function hasNativeDeflate(): boolean {
  return typeof CompressionStream !== "undefined";
}

async function deflateRaw(data: Uint8Array): Promise<Uint8Array | null> {
  if (!hasNativeDeflate()) return null;
  try {
    const cs = new CompressionStream("deflate-raw");
    const stream = new Blob([data as BlobPart]).stream().pipeThrough(cs);
    const buf = await new Response(stream).arrayBuffer();
    return new Uint8Array(buf);
  } catch {
    return null;
  }
}

export interface ZipEntry {
  /** 包内路径，用正斜杠，不要前导斜杠 */
  name: string;
  data: Uint8Array;
  /** 关掉压缩（已压缩的 PNG 之类没必要再压一遍） */
  store?: boolean;
}

interface PreparedEntry {
  nameBytes: Uint8Array;
  data: Uint8Array;
  compressed: Uint8Array;
  method: number;
  crc: number;
  offset: number;
}

function writeU32(view: DataView, offset: number, value: number): void {
  view.setUint32(offset, value >>> 0, true);
}

function writeU16(view: DataView, offset: number, value: number): void {
  view.setUint16(offset, value & 0xffff, true);
}

/**
 * 打包成 ZIP。
 *
 * 用的是无 Zip64、无数据描述符的最朴素结构 —— 3MF 阅读器兼容性最好。
 * 单个 3MF 远小于 4GB 上限，不需要 Zip64。
 */
export async function createZip(entries: ZipEntry[]): Promise<Uint8Array> {
  const encoder = new TextEncoder();
  const prepared: PreparedEntry[] = [];

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const raw = entry.data;
    let compressed = raw;
    let method = 0;

    if (!entry.store && raw.length > 0) {
      const deflated = await deflateRaw(raw);
      // 压缩没效果时（已压缩数据）就老实存储
      if (deflated && deflated.length < raw.length) {
        compressed = deflated;
        method = 8;
      }
    }

    prepared.push({
      nameBytes,
      data: raw,
      compressed,
      method,
      crc: crc32(raw),
      offset: 0,
    });
  }

  const LOCAL_HEADER = 30;
  const CENTRAL_HEADER = 46;
  const EOCD = 22;

  let localSize = 0;
  let centralSize = 0;
  for (const e of prepared) {
    localSize += LOCAL_HEADER + e.nameBytes.length + e.compressed.length;
    centralSize += CENTRAL_HEADER + e.nameBytes.length;
  }

  const out = new Uint8Array(localSize + centralSize + EOCD);
  const view = new DataView(out.buffer);
  let pos = 0;

  // ---- 本地文件头 + 数据 ----
  for (const e of prepared) {
    e.offset = pos;
    writeU32(view, pos, 0x04034b50);
    writeU16(view, pos + 4, 20); // 解压所需版本
    writeU16(view, pos + 6, 0x0800); // 文件名为 UTF-8
    writeU16(view, pos + 8, e.method);
    writeU16(view, pos + 10, 0); // 修改时间
    writeU16(view, pos + 12, 0x21); // 修改日期（固定值，保证输出可复现）
    writeU32(view, pos + 14, e.crc);
    writeU32(view, pos + 18, e.compressed.length);
    writeU32(view, pos + 22, e.data.length);
    writeU16(view, pos + 26, e.nameBytes.length);
    writeU16(view, pos + 28, 0); // 额外字段长度
    pos += LOCAL_HEADER;
    out.set(e.nameBytes, pos);
    pos += e.nameBytes.length;
    out.set(e.compressed, pos);
    pos += e.compressed.length;
  }

  // ---- 中央目录 ----
  const centralStart = pos;
  for (const e of prepared) {
    writeU32(view, pos, 0x02014b50);
    writeU16(view, pos + 4, 20); // 创建版本
    writeU16(view, pos + 6, 20); // 解压所需版本
    writeU16(view, pos + 8, 0x0800);
    writeU16(view, pos + 10, e.method);
    writeU16(view, pos + 12, 0);
    writeU16(view, pos + 14, 0x21);
    writeU32(view, pos + 16, e.crc);
    writeU32(view, pos + 20, e.compressed.length);
    writeU32(view, pos + 24, e.data.length);
    writeU16(view, pos + 28, e.nameBytes.length);
    writeU16(view, pos + 30, 0); // 额外字段
    writeU16(view, pos + 32, 0); // 注释
    writeU16(view, pos + 34, 0); // 磁盘号
    writeU16(view, pos + 36, 0); // 内部属性
    writeU32(view, pos + 38, 0); // 外部属性
    writeU32(view, pos + 42, e.offset);
    pos += CENTRAL_HEADER;
    out.set(e.nameBytes, pos);
    pos += e.nameBytes.length;
  }

  // ---- 中央目录结束记录 ----
  writeU32(view, pos, 0x06054b50);
  writeU16(view, pos + 4, 0);
  writeU16(view, pos + 6, 0);
  writeU16(view, pos + 8, prepared.length);
  writeU16(view, pos + 10, prepared.length);
  writeU32(view, pos + 12, pos - centralStart);
  writeU32(view, pos + 16, centralStart);
  writeU16(view, pos + 20, 0);

  return out;
}
