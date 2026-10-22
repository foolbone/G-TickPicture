<#
.SYNOPSIS
    G-TickPicture 开发环境体检（Windows / PowerShell 5.1+）

.DESCRIPTION
    只读检查，不修改任何东西。最后一行输出机器可读的 RESULT: PASS / RESULT: FAIL。

    重点检查项（按 2026-09-23 实际踩坑顺序）：
      1) Flutter SDK 是否存在、cache 是否就绪
      2) Android SDK 是否完整
      3) %APPDATA%\.flutter_settings 里的 android-sdk 是否有效
         —— 它优先级高于 ANDROID_HOME，指向失效路径会导致
            "Android SDK not found at this location."
      4) dart 能否创建子进程
         —— 失败则所有 flutter 命令崩溃（ERROR_PIPE_BUSY 231）

.IMPORTANT
    本文件必须保存为 UTF-8 with BOM，否则 PS 5.1 按 GBK 解码会直接 ParserError。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\env_doctor.ps1
#>

[CmdletBinding()]
param(
    [string] $FlutterDir    = '',
    [string] $AndroidSdkDir = ''
)

$ErrorActionPreference = 'Continue'
$script:FailCount = 0
$script:WarnCount = 0

function Say-Step([string]$t) {
    Write-Host ''
    Write-Host ('-' * 62) -ForegroundColor DarkGray
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ('-' * 62) -ForegroundColor DarkGray
}
function Say-Ok  ([string]$t) { Write-Host "  [ OK ] $t" -ForegroundColor Green }
function Say-Warn([string]$t) { Write-Host "  [WARN] $t" -ForegroundColor Yellow; $script:WarnCount++ }
function Say-Bad ([string]$t) { Write-Host "  [FAIL] $t" -ForegroundColor Red;   $script:FailCount++ }
function Say-Dim ([string]$t) { Write-Host "        $t" -ForegroundColor DarkGray }

Write-Host ''
Write-Host ('=' * 62) -ForegroundColor DarkGray
Write-Host '  G-TickPicture 环境体检' -ForegroundColor Cyan
Write-Host ("  " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor DarkGray
Write-Host ('=' * 62) -ForegroundColor DarkGray

# ────────────────── 0. 目录探测 ──────────────────
Say-Step '0   目录探测'

if ([string]::IsNullOrWhiteSpace($FlutterDir)) {
    $FlutterDir = @(
        'D:\dev\flutter', 'D:\flutter', 'C:\flutter',
        (Join-Path $env:USERPROFILE 'flutter')
    ) | Where-Object { Test-Path (Join-Path $_ 'bin\flutter.bat') } | Select-Object -First 1
}
if ($FlutterDir -and (Test-Path (Join-Path $FlutterDir 'bin\flutter.bat'))) {
    Say-Ok "Flutter : $FlutterDir"
} else {
    Say-Bad '未找到 Flutter（bin\flutter.bat 不存在）'
    $FlutterDir = ''
}

if ([string]::IsNullOrWhiteSpace($AndroidSdkDir)) {
    $AndroidSdkDir = @(
        $env:ANDROID_HOME, $env:ANDROID_SDK_ROOT,
        'D:\dev\Android\SDK', 'D:\dev\Andriod\SDK',
        'D:\Android\SDK', 'D:\dev\android-sdk'
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Where-Object { Test-Path (Join-Path $_ 'platform-tools') } | Select-Object -First 1
}
if ($AndroidSdkDir) {
    Say-Ok "AndroidSDK : $AndroidSdkDir"
} else {
    Say-Bad '未找到 Android SDK（platform-tools 不存在）'
}

# ────────────────── 1. Flutter SDK ──────────────────
Say-Step '1   Flutter SDK'

if ($FlutterDir) {
    $vf = Join-Path $FlutterDir 'version'
    if (Test-Path $vf) { Say-Dim ("version file : " + (Get-Content $vf -Raw).Trim()) }
    $cache = Join-Path $FlutterDir 'bin\cache'
    $dartExe = Join-Path $cache 'dart-sdk\bin\dart.exe'
    if (Test-Path $dartExe) { Say-Ok 'dart-sdk cache 就绪' } else { Say-Bad 'dart-sdk cache 缺失（首次运行 flutter 会下载）' }
    if (Test-Path (Join-Path $cache 'flutter_tools.snapshot')) { Say-Ok 'flutter_tools.snapshot 就绪' } else { Say-Warn 'flutter_tools.snapshot 缺失' }

    $g = Get-Command git -ErrorAction SilentlyContinue
    if ($g) { Say-Ok "git : $($g.Source)" } else { Say-Warn 'git 不可用（Flutter 依赖 git）' }
} else {
    Say-Bad '跳过（无 Flutter 目录）'
    $dartExe = ''
}

# ────────────────── 2. Android SDK ──────────────────
Say-Step '2   Android SDK'

if ($AndroidSdkDir) {
    $plats = @(Get-ChildItem (Join-Path $AndroidSdkDir 'platforms') -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $bts   = @(Get-ChildItem (Join-Path $AndroidSdkDir 'build-tools') -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $licN  = @(Get-ChildItem (Join-Path $AndroidSdkDir 'licenses') -ErrorAction SilentlyContinue).Count
    Say-Dim ("platforms   : " + $(if ($plats.Count) { $plats -join ', ' } else { '(none)' }))
    Say-Dim ("build-tools : " + $(if ($bts.Count)   { $bts   -join ', ' } else { '(none)' }))
    Say-Dim ("licenses    : $licN file(s)")

    if ($plats.Count -gt 0) { Say-Ok 'platforms 已安装' } else { Say-Bad 'platforms 为空' }
    if ($licN -gt 0)        { Say-Ok 'SDK 许可已接受' } else { Say-Bad 'licenses 为空（需 sdkmanager --licenses）' }
    if (Test-Path (Join-Path $AndroidSdkDir 'platform-tools\adb.exe')) { Say-Ok 'adb 存在' } else { Say-Warn 'adb 缺失' }
    if (Test-Path (Join-Path $AndroidSdkDir 'cmdline-tools\latest\bin\sdkmanager.bat')) { Say-Ok 'sdkmanager 存在' } else { Say-Warn 'sdkmanager 缺失' }
} else {
    Say-Bad '跳过（无 SDK 目录）'
}

# ────────────────── 3. flutter config（关键） ──────────────────
Say-Step '3   flutter config (android-sdk)'

$fp = Join-Path $env:APPDATA '.flutter_settings'
if (Test-Path $fp) {
    Say-Dim "file : $fp"
    try {
        $j = [IO.File]::ReadAllText($fp) | ConvertFrom-Json
        $asd = $j.'android-sdk'
        if ([string]::IsNullOrWhiteSpace($asd)) {
            Say-Warn "android-sdk 未设置（将回退 ANDROID_HOME）"
        } elseif (Test-Path $asd) {
            Say-Ok "android-sdk = $asd  (有效)"
        } else {
            Say-Bad "android-sdk = $asd  (路径不存在！会覆盖 ANDROID_HOME，必须修)"
            Say-Dim '修法：flutter config --android-sdk <正确路径>，或删掉该键'
        }
    } catch {
        Say-Warn ".flutter_settings 无法解析为 JSON"
    }
} else {
    Say-Dim '尚未生成（首次运行 flutter 时创建）'
}

$ah = [Environment]::GetEnvironmentVariable('ANDROID_HOME')
$asr = [Environment]::GetEnvironmentVariable('ANDROID_SDK_ROOT')
Say-Dim ("ANDROID_HOME     : " + $(if ($ah)  { $ah }  else { '(empty)' }))
Say-Dim ("ANDROID_SDK_ROOT : " + $(if ($asr) { $asr } else { '(empty)' }))

# ────────────────── 4. dart 子进程能力（关键） ──────────────────
Say-Step '4   dart 子进程能力（决定 flutter 命令是否可用）'

if ($dartExe -and (Test-Path $dartExe)) {
    $dv = (& $dartExe --version 2>&1 | Out-String).Trim()
    if ($dv -match 'Dart SDK version') { Say-Ok "dart 本体可用：$dv" } else { Say-Bad "dart 本体异常：$dv" }

    $probe = Join-Path $env:TEMP 'gt_probe_child.dart'
    $src = @"
import 'dart:io';
void main() {
  try {
    final r = Process.runSync('cmd', ['/c', 'ver'], runInShell: true);
    print('CHILD-OK ' + (r.stdout as String).trim());
  } catch (e) {
    print('CHILD-FAIL ' + e.toString().split('\n').first);
  }
}
"@
    [IO.File]::WriteAllText($probe, $src, (New-Object System.Text.ASCIIEncoding))
    $pr = (& $dartExe $probe 2>&1 | Out-String)
    if ($pr -match 'CHILD-OK') {
        Say-Ok 'dart 可创建子进程'
    } else {
        Say-Bad 'dart 无法创建子进程 —— 所有 flutter 命令都会崩溃 (ERROR_PIPE_BUSY 231)'
        Say-Dim '已排除：Dart 副本损坏（两套都试过）、系统管道资源（PowerShell/Python 正常）、执行沙箱（脱沙箱同样失败）'
        Say-Dim '处置顺序：'
        Say-Dim '  a) 重启电脑，重启后立刻重跑本脚本'
        Say-Dim '  b) 临时退出 360 安全卫士（主动防御）与 NordVPN（威胁防护），再重跑'
        Say-Dim '  c) 把 Flutter / Android SDK 目录加入上述软件白名单'
        Say-Dim '  d) 检查 Windows Defender 的攻击面减少(ASR)规则'
    }
} else {
    Say-Bad '跳过（无 dart.exe）'
}

# ────────────────── 5. JDK ──────────────────
Say-Step '5   JDK'

$jh = [Environment]::GetEnvironmentVariable('JAVA_HOME')
if ($jh) {
    if (Test-Path (Join-Path $jh 'bin\java.exe')) {
        $jv = (& (Join-Path $jh 'bin\java.exe') -version 2>&1 | Out-String).Trim()
        $first = ($jv -split "`n" | Where-Object { $_ -match 'version' } | Select-Object -First 1)
        Say-Ok "JAVA_HOME = $jh"
        if ($first) { Say-Dim $first.Trim() }
    } else {
        Say-Bad "JAVA_HOME = $jh 但 bin\java.exe 不存在"
    }
} else {
    Say-Warn 'JAVA_HOME 未设置'
}

# ────────────────── 汇总 ──────────────────
Write-Host ''
Write-Host ('=' * 62) -ForegroundColor DarkGray
if ($script:FailCount -eq 0) {
    Write-Host "  体检通过（$script:WarnCount 项提示）" -ForegroundColor Green
    Write-Host '  RESULT: PASS' -ForegroundColor Green
} else {
    Write-Host "  体检发现 $script:FailCount 项问题（$script:WarnCount 项提示）" -ForegroundColor Red
    Write-Host '  RESULT: FAIL' -ForegroundColor Red
}
Write-Host ('=' * 62) -ForegroundColor DarkGray

if ($script:FailCount -gt 0) { exit 1 }
