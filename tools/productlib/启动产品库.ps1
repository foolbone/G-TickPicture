# 启动产品库（绿色包）。双击同目录的「启动产品库.cmd」或本文件都行。
# 必须是 UTF-8 BOM：Windows PowerShell 5.1 会把无 BOM 的 ps1 按 GBK 解码，
# 中文乱码并让报错行号漂移。改完跑 tools/fix_ps1_bom.ps1。
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $here '集刻产品库.exe'
if (-not (Test-Path $exe)) {
  Write-Host '[FAIL] 找不到 集刻产品库.exe —— 绿色包解压不完整？请重新解压 zip' -ForegroundColor Red
  Read-Host '按回车关闭'
  exit 1
}
Write-Host '[ .. ] 正在启动产品库，浏览器会自动打开…' -ForegroundColor Cyan
Write-Host '[ .. ] 关掉这个黑窗口 = 关闭产品库。' -ForegroundColor DarkGray
Write-Host '[ .. ] 数据在 data\ 目录；换电脑把整个文件夹拷走即可。' -ForegroundColor DarkGray
Write-Host ''

# ⚠️ 端口避让**做在 exe 内部**（server._pick_port）：8765 被占用时自动往后找
#    空闲端口，并在窗口里打印实际地址 + 一条 [WARN] 说明换了端口。
#    这里**不再重复探测** —— 两处各探一套会不一致（脚本说 8766、exe 实际
#    8767），而且老板直接双击 exe 的路径根本不经过本脚本。
& $exe
$code = $LASTEXITCODE

if ($code -eq 2) {
  Write-Host ''
  Write-Host '[FAIL] 产品库没能启动（端口都被占用）。上面的提示里有三种解决办法。' -ForegroundColor Red
  Read-Host '按回车关闭'
  exit $code
}
exit $code