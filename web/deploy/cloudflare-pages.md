# 部署到 Cloudflare Pages · 操作指南

全程在浏览器里点，**不需要命令行**。做完之后：

- 网站跑在 Cloudflare 的全球 CDN 上，**你的电脑可以彻底关机**
- 免费，没有流量费，没有服务器账单
- HTTPS 证书自动签发、自动续期
- 以后 `git push` 一次，网站自动重新构建上线

> 为什么可以这样：整条解算链路都在访客自己的浏览器里跑，服务器只负责发送
> 几个静态文件。没有后端要维护，也就没有会宕机的东西。

---

## 一、创建 Pages 项目（约 3 分钟）

1. 打开 <https://dash.cloudflare.com> 登录
2. 左侧菜单 **Workers 和 Pages** → **创建** → 选 **Pages** 标签 → **连接到 Git**
3. 授权 GitHub，选择仓库 **`CMYW_Studio`**
4. 在「设置构建和部署」里，**四项必须按下表填**：

| 项目 | 填什么 |
|---|---|
| 框架预设 Framework preset | `None`（不要选 Vite，预设会覆盖下面的根目录） |
| 构建命令 Build command | `npm run build` |
| 构建输出目录 Build output directory | `dist` |
| 根目录 Root directory | `web` |

> **根目录填 `web` 是最容易漏的一项。** 代码在仓库的 `web/` 子目录里，
> 不填的话 Cloudflare 会在仓库根目录找 `package.json`，直接构建失败。

5. 点 **保存并部署**，等 1–2 分钟

构建成功后会给你一个 `xxx.pages.dev` 的地址，先点开确认网站正常。

---

## 二、换成你自己的域名 `my-gpu-node.top`

### 先删掉隧道留下的 DNS 记录（**必须先做**）

你现在的域名指向 Cloudflare Tunnel，也就是指向你的电脑。这条记录不删，
Pages 绑不上去，会提示域名已被占用。

1. Cloudflare 控制台 → 选择域名 **`my-gpu-node.top`** → 左侧 **DNS** → **记录**
2. 找到指向 `xxxxxxxx.cfargotunnel.com` 的那条 **CNAME**（名称是 `my-gpu-node.top` 或 `@`）
3. **删除**它

> 如果你还想保留隧道做别的用途，把它换个子域名（比如 `admin.my-gpu-node.top`）
> 就行，主域名让给 Pages。

### 绑定到 Pages

1. 回到 **Workers 和 Pages** → 点开你刚建的项目
2. **自定义域** → **设置自定义域**
3. 输入 `my-gpu-node.top` → **继续** → **激活域**
4. Cloudflare 会自动建好 DNS 记录并签发证书，**等 1–5 分钟**

建议把 `www` 也加上（同样步骤，输入 `www.my-gpu-node.top`），Cloudflare 会自动跳转到主域名。

---

## 三、关掉旧的东西

域名切过去、网站能正常打开之后：

1. **停掉隧道**：结束 `cloudflared.exe` 进程；如果装了开机自启，跑一下
   `web/admin_desktop/取消开机自启.bat`
2. **停掉旧网站**：结束那个 uvicorn / Python 进程
3. **电脑可以关机了** —— 网站不再依赖它

> 旧的 FastAPI 下单站（订单、后台、数据库）不在这个新站里，它是另一套东西。
> `web/data/` 里的历史订单还在你本地，**先备份再删**，别直接扔。

---

## 四、以后怎么更新网站

改完代码推上去就行，Cloudflare 会自动构建部署：

```bash
git add -A
git commit -m "改了点什么"
git push
```

推送后 1–2 分钟生效。在 Pages 项目的 **部署** 页能看到每次构建的日志。

**推之前先在本地验一遍**，省得线上构建失败：

```bash
cd web
npm run verify     # 类型检查 + 42 项测试
npm run build      # 确认能构建出来
```

---

## 出问题时

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 构建失败，日志里 `package.json not found` | 根目录没填 `web` | 项目 → 设置 → 构建和部署 → 改根目录，重新部署 |
| 构建失败，日志里 `tsc` 报错 | 类型错误 | 本地 `npm run verify` 复现并修掉 |
| 域名打不开，提示证书错误 | 证书还没签好 | 等 5 分钟；超过 15 分钟去「自定义域」看状态 |
| 域名添加不了，提示已被占用 | 隧道的 CNAME 还在 | 回第二步删掉那条记录 |
| 网站是旧的 | 浏览器缓存 | 强制刷新（Ctrl+F5） |
| 图片能显示但页面没样式 | CSP 被改坏了 | 检查 `web/public/_headers` |

---

## 顺带一提：域名本身

`my-gpu-node.top` 是个偏基础设施味道的名字（读起来像一台 GPU 服务器），
放在面向普通用户的产品站上略有落差。域名很便宜，如果以后想换个更像品牌的，
换起来就是重复一遍第二步——不影响代码，也不影响已经部署的站点。
