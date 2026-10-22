<#
.SYNOPSIS
  集刻-采集 版本发布脚本（规则见项目根目录 RELEASE.md）。

.DESCRIPTION
  按顺序完成：算新版本号 -> 校验工作区 -> 改 pubspec -> 跑门禁
  (analyze / test / 架构检查) -> 构建 release APK -> 归档并重命名
  -> git commit + git tag。

  每一步都受 -WhatIf 保护：先 -WhatIf 预演，确认无误再真跑。
  所有 flutter 命令经 tools/run_unsandboxed.ps1 执行（在 agent 会话里
  直连 flutter 会撞 ERROR_PIPE_BUSY）。

.PARAMETER Bump
  patch | minor | major | none。none = 不升版本号，只重新构建归档。

.PARAMETER SkipBuild
  跳过门禁与构建，只改版本号 + commit + tag。仅用于紧急补 tag。

.PARAMETER SkipGates
  跳过门禁 1-3（analyze/test/架构），仍构建。

.PARAMETER AllowDirty
  允许工作区有未提交改动（默认要求干净）。

.PARAMETER CommitPaths
  只把指定路径纳入发布提交（相对仓库根，逗号分隔）。
  默认是 `git add -A`，会把工作区**所有**改动都塞进发布 commit。
  什么时候需要：工作区里躺着别的会话的未提交成果（如 tools/productlib 的
  UI 改造），那批不该被一个 `chore(release): vX.Y.Z` 吞掉 ——
  混进去之后那批改动的来龙去脉就再也说不清了。
  例：`-CommitPaths 'app,CHANGELOG.md,.workbuddy/memory'`

.EXAMPLE
  .\tools\release.ps1 -Bump minor -WhatIf
  .\tools\release.ps1 -Bump minor
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [ValidateSet('patch', 'minor', 'major', 'none')]
  [string] $Bump = 'patch',

  [switch] $SkipBuild,
  [switch] $SkipGates,
  [switch] $AllowDirty,
  [string] $CommitPaths = ''
)

$ErrorActionPreference = 'Stop'

# ── 常量 ────────────────────────────────────────────────────
$root    = Split-Path -Parent $PSScriptRoot
$appDir  = Join-Path $root 'app'
$pubspec = Join-Path $appDir 'pubspec.yaml'
$flutter = 'D:\dev\flutter\bin\flutter.bat'
$runner  = Join-Path $PSScriptRoot 'run_unsandboxed.ps1'
$apkSrc  = Join-Path $appDir 'build/app/outputs/flutter-apk/app-release.apk'

function Say([string] $msg) { Write-Host $msg }
function Ok([string] $msg)  { Write-Host "  [ OK ] $msg" }
function Bad([string] $msg) { Write-Host "  [FAIL] $msg" }
function Warn([string] $msg){ Write-Host "  [WARN] $msg" }
function Skp([string] $msg) { Write-Host "  [SKIP] $msg" }

function Fail([string] $msg) {
  Bad $msg
  throw "RELEASE ABORTED: $msg"
}

# ── 1. 读当前版本 ───────────────────────────────────────────
Say '=== 1/8 读取当前版本 ==='
if (-not (Test-Path $pubspec)) { Fail "pubspec 不存在: $pubspec" }
$text = [System.IO.File]::ReadAllText($pubspec)
$m = [regex]::Match($text, '(?m)^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$')
if (-not $m.Success) { Fail "pubspec 里没找到 version: X.Y.Z+B 这一行" }

$maj = [int]$m.Groups[1].Value
$min = [int]$m.Groups[2].Value
$pat = [int]$m.Groups[3].Value
$bld = [int]$m.Groups[4].Value
$cur = "$maj.$min.$pat+$bld"
Ok "当前版本: $cur"

# 续跑检测：门禁失败中断后，pubspec 已被改过但没提交。此时工作区版本与
# HEAD 不一致 —— 必须**沿用工作区版本**，否则重启一次就把 0.7.0 推成 0.8.0。
$headVer = ''
$resume  = $false
$headRaw = & git -C $root show 'HEAD:app/pubspec.yaml' 2>$null
if ($headRaw) {
  $hm = [regex]::Match(($headRaw -join "`n"), '(?m)^version:\s*(\d+)\.(\d+)\.(\d+)\+(\d+)\s*$')
  if ($hm.Success) {
    $headVer = "$($hm.Groups[1].Value).$($hm.Groups[2].Value).$($hm.Groups[3].Value)+$($hm.Groups[4].Value)"
  }
}
if ($headVer -ne '' -and $headVer -ne $cur) {
  $resume = $true
  Warn "工作区 $cur != HEAD $headVer —— 判定为上次中断后续跑，不再升版本号"
}

if ($resume) {
  $newName = "$maj.$min.$pat"
  $newBld  = $bld
  $newVer  = $cur
  Ok "目标版本: $newVer  (续跑，版本号不动)"
} else {
  switch ($Bump) {
    'major' { $maj++; $min = 0; $pat = 0 }
    'minor' { $min++; $pat = 0 }
    'patch' { $pat++ }
    'none'  { }
  }
  $newName = "$maj.$min.$pat"
  if ($Bump -eq 'none') { $newBld = $bld } else { $newBld = $bld + 1 }
  $newVer  = "$newName+$newBld"
  Ok "目标版本: $newVer  (Bump=$Bump, versionCode $bld -> $newBld)"
}

if (-not $resume -and $Bump -ne 'none' -and $newBld -le $bld) {
  Fail 'versionCode 必须严格递增'
}

# ── 2. 工作区检查 ───────────────────────────────────────────
Say '=== 2/8 工作区检查 ==='
$porcelain = @(& git -C $root status --porcelain)
if ($resume) {
  # 续跑时 pubspec 的改动就是上次本脚本留下的，不算脏。
  $porcelain = @($porcelain | Where-Object { $_ -notlike '*app/pubspec.yaml' })
}
if ($porcelain -and -not $AllowDirty) {
  Fail "工作区不干净（-AllowDirty 可放行）：`n$($porcelain -join "`n")"
}
Ok '工作区干净'

# ── 3. 标签冲突检查 ─────────────────────────────────────────
$tag = "v$newName"
$existing = & git -C $root tag --list $tag
if ($existing) { Fail "标签 $tag 已存在（已发布的 tag 不允许重发，请升一位）" }
Ok "标签 $tag 可用"

# ── 4. CHANGELOG 检查 ───────────────────────────────────────
Say '=== 3/8 CHANGELOG 检查 ==='
$cl = Join-Path $root 'CHANGELOG.md'
if (-not (Test-Path $cl)) { Fail 'CHANGELOG.md 不存在' }
$clText = [System.IO.File]::ReadAllText($cl)
if ($clText -notmatch [regex]::Escape("## [$newName]")) {
  Fail "CHANGELOG.md 里没有 ## [$newName] 条目（门禁 5 未通过）"
}
Ok "CHANGELOG 含 [$newName] 条目"

# ── 5. 写 pubspec ───────────────────────────────────────────
Say '=== 4/8 更新 pubspec ==='
$newText = [regex]::Replace($text, '(?m)^version:\s*\d+\.\d+\.\d+\+\d+\s*$', "version: $newVer")
if ($PSCmdlet.ShouldProcess($pubspec, "version: $cur -> $newVer")) {
  [System.IO.File]::WriteAllText($pubspec, $newText)
  Ok "已写入 version: $newVer"
} else {
  Skp '未写入（预演）'
}

# ── 6. 门禁 ─────────────────────────────────────────────────
function Invoke-Gate([string] $name, [string] $flutterArgs, [int] $timeout, [string] $passPattern) {
  Say "  -> $name ..."
  $out = Join-Path $env:TEMP "gt_release_$($name -replace '\W','_').txt"
  & $runner -Command ('"' + $flutter + '" ' + $flutterArgs) -WorkingDirectory $appDir -OutFile $out -TimeoutSec $timeout | Out-Null
  $code = $LASTEXITCODE
  if (-not (Test-Path $out)) { Fail "$name 没有输出文件" }
  $tail = Get-Content $out -Tail 40
  $exitLine = $tail | Where-Object { $_ -like 'EXIT=*' } | Select-Object -Last 1
  $passed = $false
  if ($passPattern -ne '') {
    foreach ($line in $tail) { if ($line -match $passPattern) { $passed = $true; break } }
  } else { $passed = $true }

  if ($code -ne 0) { Fail "$name 退出码 $code（输出尾部：$($tail -join ' | ')）" }
  if (-not $passed) { Fail "$name 未匹配通过标志 '$passPattern'" }
  Ok "$name 通过 ($exitLine)"
}

if ($SkipBuild -or $SkipGates) {
  Say '=== 5/8 门禁（按参数跳过）==='
  Skp 'analyze / test / 架构检查'
} else {
  Say '=== 5/8 门禁 ==='
  if ($PSCmdlet.ShouldProcess('gate', 'flutter analyze')) {
    Invoke-Gate 'analyze' 'analyze' 900 'No issues found'
  } else { Skp 'analyze（预演）' }

  if ($PSCmdlet.ShouldProcess('gate', 'flutter test')) {
    Invoke-Gate 'test' 'test' 1500 'All tests passed'
  } else { Skp 'test（预演）' }

  if ($PSCmdlet.ShouldProcess('gate', 'architecture check')) {
    $archOut = & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check_architecture.ps1') *>&1 | Out-String
    if ($archOut -match 'RESULT: PASS') { Ok '架构检查通过' }
    else { Fail "架构检查未通过：`n$archOut" }
  } else { Skp '架构检查（预演）' }
}

# ── 7. 构建 ─────────────────────────────────────────────────
if ($SkipBuild) {
  Say '=== 6/8 构建（跳过）==='
  Skp 'flutter build apk --release'
} else {
  Say '=== 6/8 构建 release APK ==='
  $buildStart = Get-Date
  if ($PSCmdlet.ShouldProcess('apk', 'flutter build apk --release')) {
    $out = Join-Path $env:TEMP 'gt_release_build.txt'
    & $runner -Command ('"' + $flutter + '" build apk --release') -WorkingDirectory $appDir -OutFile $out -TimeoutSec 1800 | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "构建失败（$out）" }
    if (-not (Test-Path $apkSrc)) { Fail "产物不存在: $apkSrc" }
    $item = Get-Item $apkSrc
    if ($item.LastWriteTime -lt $buildStart.AddMinutes(-2)) {
      Fail "产物时间戳是旧的（$($item.LastWriteTime)）—— 构建可能没真正跑"
    }
    Ok "构建完成: $($item.Length) 字节 @ $($item.LastWriteTime)"
  } else { Skp '构建（预演）' }
}

# ── 8. 归档产物 ─────────────────────────────────────────────
Say '=== 7/8 归档产物 ==='
$apkDst = Join-Path $root "集刻-采集_v${newName}_release.apk"
if ($SkipBuild) {
  Skp "归档（未构建）"
} elseif ($PSCmdlet.ShouldProcess($apkDst, 'copy apk')) {
  Copy-Item -LiteralPath $apkSrc -Destination $apkDst -Force
  $d = Get-Item $apkDst
  Ok "已归档: $($d.Name)  $($d.Length) 字节"
} else { Skp '归档（预演）' }

# ── 9. commit + tag ─────────────────────────────────────────
Say '=== 8/8 提交并打标签 ==='
if ($PSCmdlet.ShouldProcess('git', "commit + tag $tag")) {
  # 限定路径时只 add 那些路径，剩下的改动**留在工作区**（不被吞进发布 commit）
  if ($CommitPaths) {
    foreach ($p in ($CommitPaths -split ',')) {
      $q = $p.Trim()
      if (-not $q) { continue }
      & git -C $root add -A -- $q
      if ($LASTEXITCODE -ne 0) { Fail "git add 失败: $q" }
    }
    $left = & git -C $root status --porcelain
    if ($left) {
      Warn "以下改动**未**纳入本次发布提交，仍在工作区："
      foreach ($l in $left) { Warn "  $l" }
    }
  } else {
    & git -C $root add -A
  }
  & git -C $root commit -q -m "chore(release): $tag"
  if ($LASTEXITCODE -ne 0) { Fail 'git commit 失败' }
  Ok "已提交: chore(release): $tag"
  & git -C $root tag -a $tag -m "集刻-采集 $tag"
  if ($LASTEXITCODE -ne 0) { Fail 'git tag 失败' }
  Ok "已打标签: $tag"
} else { Skp '提交与标签（预演）' }

Say ''
Say "=== 发布完成: $newVer (tag $tag) ==="
Say "产物: $apkDst"
Say '下一步：按 RELEASE.md 第八节做真机验收，结果回填 CHANGELOG.md。'
