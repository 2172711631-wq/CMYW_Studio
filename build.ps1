# 重新打包为可双击运行的 exe（需已安装 requirements.txt）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$AppName = "FDM灯箱生成器"
Write-Host "正在打包 $AppName..."
py -3.11 -m PyInstaller `
  --noconfirm `
  --windowed `
  --name $AppName `
  --contents-directory "_internal" `
  --collect-all open3d `
  --hidden-import=cv2 `
  --hidden-import=numpy `
  --hidden-import=shell `
  --hidden-import=bambu_export `
  --hidden-import=ui_theme `
  --hidden-import=preview_window `
  main.py

$Dist = Join-Path $Root "dist\$AppName"
if (-not (Test-Path $Dist)) {
  throw "打包失败：未找到输出目录 $Dist"
}

$TargetExe = Join-Path $Root "$AppName.exe"
Copy-Item (Join-Path $Dist "$AppName.exe") $TargetExe -Force
if (Test-Path (Join-Path $Dist "_internal")) {
  $Internal = Join-Path $Root "_internal"
  if (Test-Path $Internal) { Remove-Item $Internal -Recurse -Force }
  Copy-Item (Join-Path $Dist "_internal") $Internal -Recurse -Force
}

Write-Host "完成。可双击运行: $TargetExe"
