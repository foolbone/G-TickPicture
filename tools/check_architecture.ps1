<#
.SYNOPSIS
    架构约束校验器 —— 把设计方案里的原则变成可自动执行的检查。

.DESCRIPTION
    校验三条铁律：

      规则 1  采集期零智能（设计方案 §2.1）
              lib/domain/capture/ 下任何代码不得出现 suggest / OCR / 编码匹配相关符号。
              注释里提到这些词是允许的（描述性文字），只看代码行。

      规则 2  数据访问收口
              · UI 层（lib/ui/）不得直接 import lib/data/ 下任何文件，
                必须经由 app/providers.dart 暴露的 repository / provider。
              · 任何非 data/ 文件不得 import 生成的 database.g.dart。
              · domain/ 层允许持有 AppDatabase —— AssignService 必须自己拥有事务
                （先写 assignments 再改 itemId），这是 §6.3 的正确性落点，不是违规。

      规则 3  归属只能由人确认（§6.3）
              photo / group 的 itemId 写入（`itemId: Value(...)`）只允许出现在
              lib/domain/assign/assign_service.dart。

.IMPORTANT
    本文件必须保存为 **UTF-8 with BOM**。
    Windows PowerShell 5.1 会把无 BOM 的 .ps1 按 ANSI(GBK) 解码，
    中文变成乱码并撑破字符串引号，直接 ParserError。

    退出码 0 = 全部通过；1 = 有违规。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\check_architecture.ps1
    # 建议挂到 pre-commit 或 CI 里
#>

[CmdletBinding()]
param([string] $LibDir = 'D:\G-TickPicture\app\lib')

$ErrorActionPreference = 'Stop'
$violations = New-Object System.Collections.ArrayList

function Get-DartFiles([string]$Sub) {
    $p = Join-Path $LibDir $Sub
    if (-not (Test-Path $p)) { return @() }
    return @(Get-ChildItem -Path $p -Filter '*.dart' -Recurse -File -ErrorAction SilentlyContinue)
}

function Get-RelPath([string]$FullName) {
    return $FullName.Substring($LibDir.Length).TrimStart('\', '/').Replace('\', '/')
}

# 注释行不参与匹配：中文注释里引用"不得 import domain/suggest"这类描述性文字
# 属于合法文档，不是违规代码。
function Test-IsComment([string]$Line) {
    $t = $Line.TrimStart()
    return ($t.StartsWith('//') -or $t.StartsWith('*') -or $t.StartsWith('/*'))
}

function Add-Violation([string]$Rule, [string]$File, [int]$Line, [string]$Text) {
    [void]$violations.Add([pscustomobject]@{
        Rule = $Rule; File = $File; Line = $Line; Text = $Text.Trim()
    })
}

Write-Host ''
Write-Host '架构约束校验' -ForegroundColor Cyan
Write-Host ('─' * 62) -ForegroundColor DarkGray

# ── 规则 1：采集期零智能 ────────────────────────────────────
$capFiles = Get-DartFiles 'domain\capture'
$r1Patterns = @('domain/suggest', 'suggest_service', 'mlkit', 'ml_kit', 'text_recognition',
                'SuggestService', 'code_matcher', 'CodeMatcher')
foreach ($f in $capFiles) {
    $lines = Get-Content -LiteralPath $f.FullName -Encoding UTF8
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if (Test-IsComment $lines[$i]) { continue }
        foreach ($p in $r1Patterns) {
            if ($lines[$i] -match [regex]::Escape($p)) {
                Add-Violation 'R1 采集期零智能' $f.FullName ($i + 1) $lines[$i]
            }
        }
    }
}
Write-Host ("  规则 1  采集期零智能      扫描 {0} 个 capture 文件" -f $capFiles.Count) -ForegroundColor Gray

# ── 规则 2：数据访问收口 ────────────────────────────────────
$allDart = @(Get-ChildItem -Path $LibDir -Filter '*.dart' -Recurse -File -ErrorAction SilentlyContinue)
# 只匹配 import 语句，避免把字符串字面量里的 'data/' 误判
$r2GenPattern = '^\s*import\s+''[^'']*database\.g\.dart'''
$r2UiPattern  = '^\s*import\s+''[^'']*data/'
$r2Files = 0
$r2UiFiles = 0
foreach ($f in $allDart) {
    $rel = Get-RelPath $f.FullName
    if ($rel -like 'data/*') { continue }              # data 层是数据访问的合法家园
    $lines = Get-Content -LiteralPath $f.FullName -Encoding UTF8
    $r2Files++
    $isUi = $rel -like 'ui/*'
    if ($isUi) { $r2UiFiles++ }
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if (Test-IsComment $lines[$i]) { continue }
        if ($lines[$i] -match $r2GenPattern) {
            Add-Violation 'R2 数据访问收口（生成物越界）' $f.FullName ($i + 1) $lines[$i]
        }
        if ($isUi -and $lines[$i] -match $r2UiPattern) {
            Add-Violation 'R2 数据访问收口（UI 直连数据层）' $f.FullName ($i + 1) $lines[$i]
        }
    }
}
Write-Host ("  规则 2  数据访问收口      扫描 {0} 个非 data 文件，其中 UI 层 {1} 个" -f $r2Files, $r2UiFiles) -ForegroundColor Gray

# ── 规则 3：归属只能由 assign 层写 ──────────────────────────
$allowed = 'domain/assign/assign_service.dart'
$assignFiles = Get-DartFiles 'domain\assign'
$r3Files = 0
# 只扫描会产生「写归属」语句的位置：Companion / Value(...) 里的 itemId。
# (?<![A-Za-z0-9_]) = 参数名必须完整是 itemId —— 排除 suggestedItemId
# （建议字段由 SuggestPipeline 写是设计方案 §5.3.2 的明文设计，不是违规）。
# PowerShell -match 默认不区分大小写，不加边界会把 ItemId:/suggestedItemId: 全误伤。
$r3Pattern = '(?<![A-Za-z0-9_])itemId\s*:\s*(const\s+)?Value\('
foreach ($f in $allDart) {
    $rel = Get-RelPath $f.FullName
    if ($rel -eq $allowed) { continue }                # 唯一合法写入口
    if ($rel -like 'data/*') { continue }              # Repository 是数据层，允许
    $lines = Get-Content -LiteralPath $f.FullName -Encoding UTF8
    $r3Files++
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if (Test-IsComment $lines[$i]) { continue }
        if ($lines[$i] -match $r3Pattern) {
            Add-Violation 'R3 归属写入口唯一' $f.FullName ($i + 1) $lines[$i]
        }
    }
}
Write-Host ("  规则 3  归属写入口唯一    扫描 {0} 个文件（白名单：{1}）" -f ($r3Files + $assignFiles.Count), $allowed) -ForegroundColor Gray

# ── 汇总 ────────────────────────────────────────────────────
Write-Host ('─' * 62) -ForegroundColor DarkGray
if ($violations.Count -eq 0) {
    Write-Host '  [ OK ]  三条架构约束全部满足' -ForegroundColor Green
    Write-Host '  RESULT: PASS' -ForegroundColor Green
    exit 0
}

Write-Host "  发现 $($violations.Count) 处违规：" -ForegroundColor Red
$violations | Group-Object Rule | ForEach-Object {
    Write-Host ''
    Write-Host "  > $($_.Name)" -ForegroundColor Red
    $_.Group | ForEach-Object {
        $short = $_.File.Substring($LibDir.Length)
        Write-Host "      $short`:$($_.Line)" -ForegroundColor Yellow
        Write-Host "        $($_.Text)" -ForegroundColor DarkGray
    }
}
Write-Host ''
Write-Host '  这三条不是风格偏好，是设计方案的正确性保证，请勿绕过。' -ForegroundColor White
Write-Host "  RESULT: FAIL ($($violations.Count))" -ForegroundColor Red
exit 1
