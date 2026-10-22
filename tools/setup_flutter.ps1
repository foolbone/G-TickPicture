<#
.SYNOPSIS
    G-TickPicture 开发环境「体检 + 按需补缺」（Windows / PowerShell 5.1+）

.DESCRIPTION
    本机（2026-09-23 实探）已具备完整环境，因此本脚本的默认行为是：
    先探测、能跳过就跳过，只在缺失时才下载安装。

    已探测到的现成资产（会被自动复用，不会重装）：
      · Flutter   3.29.0 / Dart 3.7.0   @ D:\dev\flutter 或 D:\flutter
      · AndroidSDK platforms 31/33/34/35/36, build-tools x6 @ D:\dev\Android\SDK
      · JDK       21 (Android Studio jbr)

    安全说明：
      · 只做「探测 + 下载 + 配置」，不删除任何已有文件
      · 幂等：已存在的组件自动跳过，可反复执行
      · 只写「用户级」环境变量（HKCU），不需要管理员权限
      · 全程不修改系统级 PATH
      · 会修复 %APPDATA%\.flutter_settings 里失效的 android-sdk（修复前自动备份）

.IMPORTANT
    本文件必须保存为 **UTF-8 with BOM**。
    Windows PowerShell 5.1 对无 BOM 的 .ps1 会按 ANSI(GBK) 解码，
    中文全变乱码并连带撑破字符串引号，直接 ParserError。
    用编辑器改完本文件后，请确认仍带 BOM，或执行 tools/fix_ps1_bom.ps1。

.NOTES
    需要网络（仅在组件缺失时）。全新安装约 1.2 GB，10~25 分钟。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\setup_flutter.ps1
    指定目录：-FlutterDir E:\dev\flutter -AndroidSdkDir E:\dev\android-sdk
    需要模拟器：加 -WithEmulator（多约 1.2 GB）
#>

[CmdletBinding()]
param(
    [string] $FlutterDir     = '',                      # 空 = 自动探测
    [string] $AndroidSdkDir  = '',                      # 空 = 自动探测
    [string] $FlutterMirror  = 'https://storage.flutter-io.cn',
    [string] $PubMirror      = 'https://pub.flutter-io.cn',
    [string] $Channel        = 'stable',
    [string] $AndroidBuildTools = '35.0.0',
    [int]    $AndroidPlatform   = 35,
    [switch] $WithEmulator          # 默认不装模拟器（约 1.2 GB，真机调试用不上）
)

$ErrorActionPreference = 'Stop'
$script:Failed = @()

# ═══════════════════════════ 工具函数 ═══════════════════════════

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host ('-' * 62) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('-' * 62) -ForegroundColor DarkGray
}
function Write-Ok  ([string]$Text) { Write-Host "  [ OK ] $Text" -ForegroundColor Green }
function Write-Skip([string]$Text) { Write-Host "  [SKIP] $Text" -ForegroundColor DarkGray }
function Write-Warn([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Bad ([string]$Text) { Write-Host "  [FAIL] $Text" -ForegroundColor Red; $script:Failed += $Text }

function Add-UserPath([string]$Dir) {
    if ([string]::IsNullOrWhiteSpace($Dir)) { return }
    if (-not (Test-Path $Dir)) { return }
    $cur = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrEmpty($cur)) { $cur = '' }
    $parts = @($cur -split ';' | Where-Object { $_ -ne '' })
    if ($parts -notcontains $Dir) {
        [Environment]::SetEnvironmentVariable('Path', (($parts + $Dir) -join ';'), 'User')
        Write-Ok "已加入用户 PATH: $Dir"
    } else {
        Write-Skip "用户 PATH 已包含: $Dir"
    }
    if (($env:Path -split ';') -notcontains $Dir) { $env:Path = "$env:Path;$Dir" }
}

function Set-UserEnv([string]$Name, [string]$Value) {
    [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
    Set-Item -Path "Env:$Name" -Value $Value
    Write-Ok "$Name = $Value"
}

function Get-File([string]$Url, [string]$OutFile) {
    if (Test-Path $OutFile) { Write-Skip "已存在，跳过下载：$(Split-Path $OutFile -Leaf)"; return }
    $dir = Split-Path $OutFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Write-Host "  下载：$Url" -ForegroundColor DarkCyan
    try {
        Start-BitsTransfer -Source $Url -Destination $OutFile -ErrorAction Stop
    } catch {
        $old = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'   # 关进度条可显著加速 IWR
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
        $ProgressPreference = $old
    }
    $mb = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
    Write-Ok "下载完成：$(Split-Path $OutFile -Leaf) ($mb MB)"
}

function Expand-Zip([string]$Zip, [string]$Dest) {
    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }
    Expand-Archive -Path $Zip -DestinationPath $Dest -Force
}

# 修正 %APPDATA%\.flutter_settings 里失效的 android-sdk。
#
# 为什么需要它：flutter 定位 Android SDK 的优先级是
#   config['android-sdk']  >  ANDROID_HOME  >  ANDROID_SDK_ROOT  >  aapt/adb 反推
# 只要 config 里存了一个「存在但无效」的路径，环境变量就会被完全忽略，
# 而 flutter 会退到 whichAll('aapt') 去猜——若此时子进程管道异常，就直接崩栈。
# 2026-09-23 本机即因此报 "Android SDK not found at this location."。
function Repair-FlutterSettings([string]$SdkDir) {
    if ([string]::IsNullOrWhiteSpace($SdkDir)) { return }
    $p = Join-Path $env:APPDATA '.flutter_settings'
    if (-not (Test-Path $p)) { Write-Skip ".flutter_settings 尚未生成（首次运行 flutter 时创建），跳过"; return }

    $raw = [IO.File]::ReadAllText($p)
    try { $obj = $raw | ConvertFrom-Json } catch {
        Write-Warn ".flutter_settings 不是合法 JSON，跳过修复（不修改该文件）"
        return
    }

    $cur = $obj.'android-sdk'
    if ($cur -eq $SdkDir) { Write-Skip "flutter config 已正确指向 $SdkDir"; return }
    if (-not [string]::IsNullOrWhiteSpace($cur) -and (Test-Path $cur)) {
        Write-Skip "flutter config 已有有效路径，保持不变：$cur"
        return
    }

    Copy-Item $p "$p.bak" -Force
    if ($obj.PSObject.Properties.Name -contains 'android-sdk') {
        $obj.'android-sdk' = $SdkDir
    } else {
        $obj | Add-Member -NotePropertyName 'android-sdk' -NotePropertyValue $SdkDir
    }
    # 必须写「无 BOM」UTF-8：Dart 的 jsonDecode 不接受 BOM
    [IO.File]::WriteAllText($p, ($obj | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok "已修正 flutter config：android-sdk = $SdkDir"
    if (-not [string]::IsNullOrWhiteSpace($cur)) { Write-Host "         原值无效：$cur" -ForegroundColor DarkGray }
}

# ═══════════════════════════ 0. 探测与检查 ═══════════════════════════

Write-Step '0 / 6   环境探测'

if ($PSVersionTable.PSVersion.Major -lt 5) { throw '需要 PowerShell 5.1 或更高版本。' }
Write-Ok "PowerShell $($PSVersionTable.PSVersion)"

# ── Flutter 目录：自动探测（不覆盖已存在的）──
if ([string]::IsNullOrWhiteSpace($FlutterDir)) {
    $cand = @(
        'D:\dev\flutter', 'D:\flutter', 'C:\flutter',
        (Join-Path $env:USERPROFILE 'flutter'),
        (Join-Path $env:LOCALAPPDATA 'flutter')
    ) | Where-Object { Test-Path (Join-Path $_ 'bin\flutter.bat') } | Select-Object -First 1

    if ($cand) {
        $FlutterDir = $cand
        Write-Ok "探测到 Flutter：$FlutterDir"
        $vf = Join-Path $FlutterDir 'version'
        if (Test-Path $vf) { Write-Host "         版本 $((Get-Content $vf -Raw).Trim())" -ForegroundColor DarkGray }
    } else {
        $FlutterDir = 'D:\dev\flutter'
        Write-Warn "未探测到 Flutter，将在 $FlutterDir 全新安装"
    }
}

# ── Android SDK 目录：自动探测 ──
if ([string]::IsNullOrWhiteSpace($AndroidSdkDir)) {
    # 第一优先：环境变量里已配置且确实有效的
    # 第二优先：本机已知位置（注意历史上目录名被拼成 Andriod，两个都认）
    $cand = @(
        $env:ANDROID_HOME,
        $env:ANDROID_SDK_ROOT,
        'D:\dev\Android\SDK', 'D:\dev\Andriod\SDK',
        'D:\Android\SDK', 'D:\Andriod\SDK',
        'D:\dev\android-sdk', 'D:\android-sdk',
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Sort-Object -Unique |
        Where-Object { Test-Path (Join-Path $_ 'platform-tools') } |
        Select-Object -First 1

    if ($cand) {
        $AndroidSdkDir = $cand
        Write-Ok "探测到 Android SDK：$AndroidSdkDir"
    } else {
        $AndroidSdkDir = 'D:\dev\android-sdk'
        Write-Warn "未探测到 Android SDK，将在 $AndroidSdkDir 全新安装"
    }
}

$roots = @($FlutterDir, $AndroidSdkDir) | Where-Object { $_ } | ForEach-Object { Split-Path $_ -Qualifier }
foreach ($r in ($roots | Sort-Object -Unique)) {
    try {
        $free = (Get-PSDrive ($r.TrimEnd(':'))).Free / 1GB
        if ($free -lt 8) { Write-Warn "$r 仅剩 $([math]::Round($free,1)) GB，建议预留 8 GB 以上" }
        else { Write-Ok "$r 可用空间 $([math]::Round($free,1)) GB" }
    } catch { Write-Warn "无法读取 $r 可用空间" }
}

$hasGit = $null -ne (Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit) { Write-Ok 'git 可用（Flutter 依赖 git 做版本管理）' }
else { Write-Warn '未检测到 git。将改用 zip 方式安装 Flutter（官方推荐用 git）' }

# ═══════════════════════════ 1. Flutter SDK ═══════════════════════════

Write-Step '1 / 6   Flutter SDK'

$flutterBat = Join-Path $FlutterDir 'bin\flutter.bat'

if (Test-Path $flutterBat) {
    Write-Skip "Flutter 已存在，复用：$FlutterDir"
} else {
    $parent = Split-Path $FlutterDir -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    $installed = $false

    if ($hasGit) {
        Write-Host "  git clone $Channel 分支 -> $FlutterDir" -ForegroundColor DarkCyan
        try {
            & git clone --branch $Channel --single-branch https://github.com/flutter/flutter.git $FlutterDir
            if (Test-Path $flutterBat) { $installed = $true; Write-Ok 'git 方式安装完成' }
        } catch { Write-Warn "git clone 失败：$($_.Exception.Message)" }
    }

    if (-not $installed) {
        Write-Host '  改用镜像 zip 方式...' -ForegroundColor DarkCyan
        try {
            $meta = Invoke-RestMethod -Uri "$FlutterMirror/flutter_infra_release/releases/releases_windows.json" -TimeoutSec 60
            $hash = $meta.current_release.$Channel
            $rel  = $meta.releases | Where-Object { $_.hash -eq $hash } | Select-Object -First 1
            if (-not $rel) { throw "在 releases_windows.json 里找不到 $Channel 的当前版本" }
            Write-Ok "目标版本：$($rel.version) ($Channel)"
            $zipUrl  = "$FlutterMirror/flutter_infra_release/releases/$($rel.archive)"
            $zipPath = Join-Path $env:TEMP "flutter_$($rel.version)_$Channel.zip"
            Get-File -Url $zipUrl -OutFile $zipPath
            Expand-Zip -Zip $zipPath -Dest $parent      # zip 内是 flutter/ 一层
            if (Test-Path $flutterBat) { $installed = $true; Write-Ok 'zip 方式安装完成' }
        } catch { Write-Bad "Flutter 下载失败：$($_.Exception.Message)" }
    }

    if (-not $installed -and -not (Test-Path $flutterBat)) {
        Write-Bad 'Flutter 安装未完成。请手工下载后解压到该目录，再重跑本脚本。'
    }
}

if (Test-Path $flutterBat) { Add-UserPath (Join-Path $FlutterDir 'bin') }

# ═══════════════════════════ 2. 国内镜像 ═══════════════════════════

Write-Step '2 / 6   国内镜像'

Set-UserEnv 'PUB_HOSTED_URL'            $PubMirror
Set-UserEnv 'FLUTTER_STORAGE_BASE_URL'  $FlutterMirror

# ═══════════════════════════ 3. Android 命令行工具 ═══════════════════════════

Write-Step '3 / 6   Android 命令行工具'

$cmdlineToolsDir = Join-Path $AndroidSdkDir 'cmdline-tools\latest'
$sdkManager      = Join-Path $cmdlineToolsDir 'bin\sdkmanager.bat'

if (Test-Path $sdkManager) {
    Write-Skip "cmdline-tools 已存在，复用：$cmdlineToolsDir"
} else {
    # 如需固定版本可改这个 URL；Google 会不定期更新文件名中的版本号
    $ctUrl = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
    try {
        $ctZip = Join-Path $env:TEMP 'android_cmdline_tools.zip'
        Get-File -Url $ctUrl -OutFile $ctZip

        $stage = Join-Path $env:TEMP ('android_ct_' + [guid]::NewGuid().ToString('N'))
        Expand-Zip -Zip $ctZip -Dest $stage
        $inner = Join-Path $stage 'cmdline-tools'

        $targetParent = Split-Path $cmdlineToolsDir -Parent
        if (-not (Test-Path $targetParent)) { New-Item -ItemType Directory -Path $targetParent -Force | Out-Null }

        if (Test-Path $inner) {
            if (-not (Test-Path $cmdlineToolsDir)) {
                Move-Item -Path $inner -Destination $cmdlineToolsDir
                Write-Ok "cmdline-tools -> $cmdlineToolsDir"
            } else { Write-Skip "目标已存在，跳过移动：$cmdlineToolsDir" }
        } else { Write-Bad '解压后未找到 cmdline-tools 目录，压缩包结构与预期不符' }
    } catch { Write-Bad "cmdline-tools 安装失败：$($_.Exception.Message)" }
}

Add-UserPath (Join-Path $AndroidSdkDir 'platform-tools')
Add-UserPath (Join-Path $AndroidSdkDir 'cmdline-tools\latest\bin')

Set-UserEnv 'ANDROID_HOME'     $AndroidSdkDir
Set-UserEnv 'ANDROID_SDK_ROOT' $AndroidSdkDir

# JDK：Flutter / Gradle 需要 JAVA_HOME。优先复用 Android Studio 自带的 JBR，不必另装。
$userJava = [Environment]::GetEnvironmentVariable('JAVA_HOME', 'User')
if (-not $userJava -and -not $env:JAVA_HOME) {
    $jbrCand = @(@(
        'C:\Program Files\Android\Android Studio\jbr',
        'C:\Program Files (x86)\Android\Android Studio\jbr'
    ) | Where-Object { Test-Path (Join-Path $_ 'bin\java.exe') })
    if ($jbrCand.Count -gt 0) {
        Set-UserEnv 'JAVA_HOME' $jbrCand[0]
    } else {
        Write-Warn '未检测到 JDK。请安装 Android Studio 后重跑本脚本，或手工设置 JAVA_HOME'
    }
} else {
    Write-Skip 'JAVA_HOME 已配置，保持不变'
}

# ═══════════════════════════ 4. SDK 组件与许可 ═══════════════════════════

Write-Step '4 / 6   SDK 组件与许可'

if (Test-Path $sdkManager) {
    # 先算缺口，已齐则完全不调 sdkmanager（快且不惹网络）
    $needPkgs = @()
    if (-not (Test-Path (Join-Path $AndroidSdkDir 'platform-tools')))                        { $needPkgs += 'platform-tools' }
    if (-not (Test-Path (Join-Path $AndroidSdkDir "platforms\android-$AndroidPlatform")))    { $needPkgs += "platforms;android-$AndroidPlatform" }
    if (-not (Test-Path (Join-Path $AndroidSdkDir "build-tools\$AndroidBuildTools")))        { $needPkgs += "build-tools;$AndroidBuildTools" }
    if ($WithEmulator -and -not (Test-Path (Join-Path $AndroidSdkDir 'emulator')))           { $needPkgs += 'emulator' }

    $licDir = Join-Path $AndroidSdkDir 'licenses'
    $hasLic = (Test-Path $licDir) -and ((Get-ChildItem $licDir -ErrorAction SilentlyContinue).Count -gt 0)

    if ($needPkgs.Count -eq 0 -and $hasLic) {
        Write-Skip 'SDK 组件与许可已齐备，无需调用 sdkmanager'
    } else {
        try {
            if (-not $hasLic) {
                Write-Host '  接受 Android SDK 许可（自动输入 y）...' -ForegroundColor DarkCyan
                # 逐行喂 'y'，比拼成一个长字符串更稳（部分 .bat 只读第一行）
                $answers = @(1..40 | ForEach-Object { 'y' })
                $answers | & $sdkManager --sdk_root="$AndroidSdkDir" --licenses 2>&1 | Out-Null
                Write-Ok '许可已接受'
            } else {
                Write-Skip 'SDK 许可已存在'
            }

            foreach ($p in $needPkgs) {
                Write-Host "  安装 $p ..." -ForegroundColor DarkCyan
                & $sdkManager --sdk_root="$AndroidSdkDir" $p 2>&1 | Out-Null
                Write-Ok "已安装 $p"
            }
        } catch { Write-Bad "SDK 组件安装失败：$($_.Exception.Message)" }
    }
} else {
    Write-Bad 'sdkmanager 不可用，跳过组件安装'
}

# ═══════════════════════════ 5. 关联 Android SDK ═══════════════════════════

Write-Step '5 / 6   关联 Android SDK'

# 先做「文件级」修复：不依赖 flutter 命令可用
Repair-FlutterSettings $AndroidSdkDir

if (Test-Path $flutterBat) {
    $probe = & $flutterBat --no-version-check config --android-sdk "$AndroidSdkDir" 2>&1 | Out-String
    if ($probe -match 'CreateFile failed|ProcessException') {
        Write-Warn 'flutter 命令当前无法创建子进程，已改由配置文件完成关联（见上方修复结果）'
        Write-Host '         详见第 6 步的处置建议。' -ForegroundColor DarkGray
    } else {
        Write-Ok 'flutter config --android-sdk 已执行'
        & $flutterBat --no-version-check config --no-analytics 2>&1 | Out-Null
        Write-Host '  首次运行 flutter --version（初始化 Dart SDK，约 1~3 分钟）...' -ForegroundColor DarkCyan
        & $flutterBat --no-version-check --version 2>&1 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    }
} else {
    Write-Bad 'flutter 不可用，跳过关联'
}

# ═══════════════════════════ 6. 验证 ═══════════════════════════

Write-Step '6 / 6   验证'

$pipeBroken = $false
if (Test-Path $flutterBat) {
    $probe = & $flutterBat --no-version-check --version 2>&1 | Out-String
    if ($probe -match 'CreateFile failed|ProcessException') {
        $pipeBroken = $true
        Write-Bad 'flutter 命令无法创建子进程（Windows 错误 231 = ERROR_PIPE_BUSY）'
        Write-Host ''
        Write-Host '  这不是 Flutter/SDK 安装问题——Dart 本体可用，系统管道也正常，' -ForegroundColor Yellow
        Write-Host '  是「Dart 创建子进程的命名管道」被拦截。已知嫌疑：' -ForegroundColor Yellow
        Write-Host '    1) 360 安全卫士（360tray / ZhuDongFangYu 主动防御）' -ForegroundColor Yellow
        Write-Host '    2) NordVPN Threat Protection（nord-security-* 管道 40+ 个）' -ForegroundColor Yellow
        Write-Host '    3) 其他带进程 hook 的安全/网络组件' -ForegroundColor Yellow
        Write-Host ''
        Write-Host '  处置顺序（从省事到彻底）：' -ForegroundColor White
        Write-Host '    a) 重启电脑，重启后立刻重跑本脚本' -ForegroundColor White
        Write-Host '    b) 临时退出 360 主动防御 / NordVPN 威胁防护，再重跑' -ForegroundColor White
        Write-Host '    c) 把以下目录加入白名单后重跑：' -ForegroundColor White
        Write-Host "         $FlutterDir" -ForegroundColor Gray
        Write-Host "         $AndroidSdkDir" -ForegroundColor Gray
        Write-Host ''
    } else {
        Write-Host '  flutter doctor -v 输出如下：' -ForegroundColor DarkCyan
        Write-Host ''
        & $flutterBat --no-version-check doctor -v 2>&1 | ForEach-Object { Write-Host "  $_" }
    }
} else {
    Write-Bad 'flutter 不可用，无法执行验证'
}

Write-Host ''
Write-Host ('=' * 62) -ForegroundColor DarkGray
if ($pipeBroken) {
    Write-Host '  环境资产已就绪，但 flutter 命令暂不可用（见上方处置建议）' -ForegroundColor Yellow
} elseif ($script:Failed.Count -eq 0) {
    Write-Host '  体检完成，环境可用' -ForegroundColor Green
    Write-Host '  请【关闭并重新打开】终端，然后执行：' -ForegroundColor White
    Write-Host '      cd D:\G-TickPicture' -ForegroundColor White
    Write-Host '      powershell -ExecutionPolicy Bypass -File .\tools\init_project.ps1' -ForegroundColor White
} else {
    Write-Host "  有 $($script:Failed.Count) 项未完成：" -ForegroundColor Yellow
    $script:Failed | ForEach-Object { Write-Host "    - $_" -ForegroundColor Yellow }
    Write-Host ''
    Write-Host '  手工兜底：' -ForegroundColor White
    Write-Host '    1) Flutter 手工下载：https://storage.flutter-io.cn/flutter_infra_release/releases/' -ForegroundColor Gray
    Write-Host "       解压到 $FlutterDir（保证 bin\flutter.bat 存在）" -ForegroundColor Gray
    Write-Host '    2) Android 命令行工具：https://developer.android.com/studio#command-tools' -ForegroundColor Gray
    Write-Host "       解压到 $AndroidSdkDir\cmdline-tools\latest" -ForegroundColor Gray
    Write-Host '    3) 重跑本脚本，已存在的组件会自动跳过' -ForegroundColor Gray
}
Write-Host ('=' * 62) -ForegroundColor DarkGray

if ($script:Failed.Count -gt 0) { exit 1 }
