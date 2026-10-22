<#
.SYNOPSIS
    初始化 G-TickPicture 工程：补齐 android/ 平台目录，然后拉依赖、跑代码生成。

.DESCRIPTION
    骨架里的 lib/ 与 pubspec.yaml 是手工编写的成果物，不能被 flutter create 覆盖。
    所以本脚本的流程是：
        备份 lib/ + pubspec.yaml
          → flutter create .（只为了生成 android/ 等平台目录）
          → 还原 lib/ + pubspec.yaml
          → flutter pub get
          → dart run build_runner build（生成 database.g.dart）
          → flutter analyze

    安全：只在自己工程目录内操作；还原后原文件内容与执行前完全一致。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\init_project.ps1
#>

[CmdletBinding()]
param(
    [string] $AppDir   = 'D:\G-TickPicture\app',
    [string] $Org      = 'com.gtick',
    [string] $ProjName = 'g_tick_picture',
    [switch] $SkipCodegen
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$t) {
    Write-Host ''
    Write-Host ('─' * 62) -ForegroundColor DarkGray
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ('─' * 62) -ForegroundColor DarkGray
}
function Write-Ok ([string]$t) { Write-Host "  [ OK ] $t" -ForegroundColor Green }
function Write-Warn([string]$t) { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Write-Bad ([string]$t) { Write-Host "  [FAIL] $t" -ForegroundColor Red }

# ── 0. 前置检查 ─────────────────────────────────────────────
Write-Step '0 / 6   前置检查'

if (-not (Test-Path $AppDir)) { throw "工程目录不存在：$AppDir" }
Set-Location $AppDir
Write-Ok "工作目录：$AppDir"

$flutter = Get-Command flutter -ErrorAction SilentlyContinue
if (-not $flutter) {
    throw '未找到 flutter 命令。请先运行 tools/setup_flutter.ps1，并【重开终端】使 PATH 生效。'
}
Write-Ok "flutter → $($flutter.Source)"

if (-not (Test-Path (Join-Path $AppDir 'lib\main.dart'))) {
    Write-Warn 'lib\main.dart 不存在 —— 骨架文件缺失，请先确认 skeleton 已铺好'
}

# 确认骨架文件齐全
$must = @('pubspec.yaml', 'analysis_options.yaml', 'lib\main.dart', 'lib\app\router.dart',
          'lib\data\db\tables.dart', 'lib\data\db\database.dart')
$missing = $must | Where-Object { -not (Test-Path (Join-Path $AppDir $_)) }
if ($missing.Count -gt 0) { throw "骨架文件缺失：$($missing -join ', ')" }
Write-Ok "骨架文件齐全（$($must.Count) 个关键文件）"

# ── 1. 备份骨架 ─────────────────────────────────────────────
Write-Step '1 / 6   备份骨架文件'

$backup = Join-Path $env:TEMP ('gtick_bak_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item (Join-Path $AppDir 'lib')            -Destination $backup -Recurse -Force
Copy-Item (Join-Path $AppDir 'pubspec.yaml')   -Destination $backup -Force
Copy-Item (Join-Path $AppDir 'analysis_options.yaml') -Destination $backup -Force
Write-Ok "已备份到 $backup"

# ── 2. flutter create 补齐平台目录 ──────────────────────────
Write-Step '2 / 6   生成 android/ 平台目录'

try {
    & flutter create . --org $Org --project-name $ProjName --platforms android --overwrite
    if ($LASTEXITCODE -ne 0) { throw "flutter create 退出码 $LASTEXITCODE" }
    Write-Ok 'android/ 生成完毕'
} catch {
    Write-Bad "flutter create 失败：$($_.Exception.Message)"
}

# ── 3. 还原骨架 ─────────────────────────────────────────────
Write-Step '3 / 6   还原骨架文件'

# 先验备份完整性，再动原目录 —— 备份坏了就一票否决，绝不留「删了没得还」的中间态
$bakLib = Join-Path $backup 'lib'
if (-not (Test-Path (Join-Path $bakLib 'main.dart'))) {
    throw "备份不完整，已中止（未删除任何文件）：$bakLib"
}

Remove-Item (Join-Path $AppDir 'lib') -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $bakLib -Destination $AppDir -Recurse -Force
Copy-Item (Join-Path $backup 'pubspec.yaml') -Destination $AppDir -Force
Copy-Item (Join-Path $backup 'analysis_options.yaml') -Destination $AppDir -Force
Write-Ok 'lib/ 与 pubspec.yaml 已还原为骨架版本'

# ── 4. pub get ─────────────────────────────────────────────
Write-Step '4 / 6   拉取依赖'
& flutter pub get
if ($LASTEXITCODE -ne 0) {
    Write-Warn 'pub get 失败。常见原因是依赖版本号与当前 pub.dev 不匹配，执行下面这条自动对齐：'
    Write-Host '      flutter pub upgrade --major-versions' -ForegroundColor White
    throw 'pub get 未通过，已停止。'
}
Write-Ok 'pub get 通过'

# ── 5. 代码生成 ─────────────────────────────────────────────
if (-not $SkipCodegen) {
    Write-Step '5 / 6   生成 drift 代码（database.g.dart）'
    & dart run build_runner build --delete-conflicting-outputs
    if ($LASTEXITCODE -ne 0) { Write-Bad 'build_runner 失败，database.g.dart 未生成，工程无法编译' }
    else {
        $g = Get-ChildItem -Path (Join-Path $AppDir 'lib') -Filter 'database.g.dart' -Recurse -ErrorAction SilentlyContinue
        if ($g) { Write-Ok "已生成 $($g[0].FullName)（$([math]::Round($g[0].Length/1KB,1)) KB）" }
        else    { Write-Bad 'build_runner 跑完但找不到 database.g.dart' }
    }
} else {
    Write-Step '5 / 6   已跳过代码生成'
}

# ── 6. analyze ─────────────────────────────────────────────
Write-Step '6 / 6   静态分析'
& flutter analyze
switch ($LASTEXITCODE) {
    0 { Write-Ok 'flutter analyze 通过，零问题' }
    default { Write-Warn "flutter analyze 报出问题（退出码 $LASTEXITCODE），按提示逐个修" }
}

Write-Host ''
Write-Host ('═' * 62) -ForegroundColor DarkGray
Write-Host '  下一步：' -ForegroundColor White
Write-Host '      flutter devices          # 确认手机已连上（开 USB 调试）' -ForegroundColor White
Write-Host '      flutter run              # 装到手机上看效果' -ForegroundColor White
Write-Host '      flutter build apk --release --split-per-abi' -ForegroundColor White
Write-Host ('═' * 62) -ForegroundColor DarkGray
Write-Host "  骨架备份仍在：$backup（确认无误后可删）" -ForegroundColor DarkGray
