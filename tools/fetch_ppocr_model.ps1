<#
.SYNOPSIS
    下载 PP-OCRv6 的端侧 ONNX 模型与识别字典，放进 Android assets。

.DESCRIPTION
    ═══════════════════════════════════════════════════════════════
    这个脚本解决的是一个**非对称**问题：
      · 代码（Kotlin + Dart）在仓库里，随时可读；
      · 模型文件（30 MB 二进制）**不能进版本控制**，但又是运行期必需品。
    所以做成"要用的时候跑一下"。

    缺模型**不会导致编译失败** —— PpOcrEngine.create() 返回 null，
    Dart 侧静默回退 ML Kit（lib/domain/ocr/ocr_engine_factory.dart）。

    ═══════════════════════════════════════════════════════════════
    来源：ModelScope（hf-mirror / huggingface.co 在国内多数网络不通）
    ───────────────────────────────────────────────────────────────
      PaddlePaddle/PP-OCRv6_small_det_onnx  ->  assets/ppocr/det.onnx
      PaddlePaddle/PP-OCRv6_small_rec_onnx  ->  assets/ppocr/rec.onnx
      rec 包的 inference.yml 里的 character_dict -> assets/ppocr/keys.txt

    ⚠️ 官方发布的是 **Paddle 推理格式**（inference.json + inference.pdiparams，
       即 Paddle 3.0 的 PIR 格式，没有 .pdmodel），**不是 .onnx**。
       上面的两个 ModelScope 仓库是官方**已转好的 ONNX 版本**，
       所以本脚本**不需要** paddle2onnx，直接下 .onnx 即可。

    ═══════════════════════════════════════════════════════════════
    三个容易踩的坑（都是实测踩出来的）
    ───────────────────────────────────────────────────────────────
    1. **keys.txt 必须写成无 BOM 的 UTF-8**。带 BOM 会让第一个字符变成
       BOM + 字符，识别结果从第一个字就错。所以这里用 UTF8Encoding($false)，
       不能用 `-Encoding utf8`（PS 5.1 的 utf8 是带 BOM 的）。
    2. **解析 character_dict 时不能用 Trim()**。字典第 1748 条是
       U+3000 全角空格「　」，而 .NET 的 Trim() 会剥掉 Unicode 空白，
       把它读成空串 —— 后面 17000 多个字符的下标会整体前移，
       输出整片乱码且**不报错**。这里只用 Substring。
    3. **字典长度必须等于 rec.onnx 输出的最后一维**（18710）：
       1 个 CTC blank + 18708 个字典字符 + 1 个半角空格。
       对不上说明模型/字典版本不匹配，脚本直接判定失败。

.PARAMETER Mode
    check   只检查现状（含 sha256 与字典长度校验），不下载（默认）
    fetch   下载缺失或校验不通过的文件
    clean   删掉已下载的模型与字典

.PARAMETER Force
    已存在且校验通过的文件也重新下载。

.EXAMPLE
    .\tools\fetch_ppocr_model.ps1 -Mode check
    .\tools\fetch_ppocr_model.ps1 -Mode fetch

.IMPORTANT
    本文件必须保存为 **UTF-8 with BOM**（否则 PS 5.1 按 GBK 解码报错）。
    改完跑 tools/fix_ps1_bom.ps1。
#>

[CmdletBinding()]
param(
    [ValidateSet('check', 'fetch', 'clean')]
    [string] $Mode = 'check',

    [switch] $Force
)

$ErrorActionPreference = 'Stop'

$root     = Split-Path $PSScriptRoot -Parent
$assetDir = Join-Path $root 'app\android\app\src\main\assets\ppocr'
$workDir  = Join-Path $env:TEMP 'ppocr_fetch'

# ── 已知来源（改动这两行即可换模型版本）────────────────────────
$MsBase = 'https://www.modelscope.cn/api/v1/models/PaddlePaddle'
$DetRepo = 'PP-OCRv6_small_det_onnx'
$RecRepo = 'PP-OCRv6_small_rec_onnx'

$DetSha = 'd73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e'
$RecSha = '5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634'

# rec.onnx 输出的最后一维（类别数）。字典布局：1 blank + N 字典 + 1 空格。
$ExpectedClasses = 18710
$ExpectedDict    = $ExpectedClasses - 2   # 18708

function Write-Note([string]$m) { Write-Host "  $m" }
function Write-Ok([string]$m)   { Write-Host "  [ OK ] $m"   -ForegroundColor Green }
function Write-Warn2([string]$m){ Write-Host "  [WARN] $m"   -ForegroundColor Yellow }
function Write-Err([string]$m)  { Write-Host "  [FAIL] $m"   -ForegroundColor Red }

function Get-Sha256([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

Write-Host ''
Write-Host 'PP-OCRv6 模型准备' -ForegroundColor Cyan
Write-Host ('-' * 62) -ForegroundColor DarkGray
Write-Note "目标目录: $assetDir"

# ── clean ────────────────────────────────────────────────────
if ($Mode -eq 'clean') {
    if (Test-Path $assetDir) {
        Get-ChildItem -LiteralPath $assetDir -File | ForEach-Object {
            if ($_.Name -ne 'README.txt') { Remove-Item -LiteralPath $_.FullName -Force }
        }
        Write-Ok "已清空 $assetDir （保留 README.txt）"
    } else {
        Write-Note '目录本来就不存在，无需清理。'
    }
    Write-Host ''
    exit 0
}

# ── 现状检查 ─────────────────────────────────────────────────
$needDet  = $true
$needRec  = $true
$needKeys = $true

$detPath  = Join-Path $assetDir 'det.onnx'
$recPath  = Join-Path $assetDir 'rec.onnx'
$keysPath = Join-Path $assetDir 'keys.txt'

if (Test-Path $detPath) {
    $s = Get-Sha256 $detPath
    if ($s -eq $DetSha) {
        Write-Ok "det.onnx  ($([Math]::Round((Get-Item $detPath).Length / 1MB, 2)) MB, sha256 匹配)"
        $needDet = $false
    } else {
        Write-Warn2 "det.onnx  存在但 sha256 不匹配（期望 $($DetSha.Substring(0,16))…，实际 $($s.Substring(0,16))…）"
    }
} else { Write-Warn2 'det.onnx  缺失' }

if (Test-Path $recPath) {
    $s = Get-Sha256 $recPath
    if ($s -eq $RecSha) {
        Write-Ok "rec.onnx  ($([Math]::Round((Get-Item $recPath).Length / 1MB, 2)) MB, sha256 匹配)"
        $needRec = $false
    } else {
        Write-Warn2 "rec.onnx  存在但 sha256 不匹配（期望 $($RecSha.Substring(0,16))…，实际 $($s.Substring(0,16))…）"
    }
} else { Write-Warn2 'rec.onnx  缺失' }

if (Test-Path $keysPath) {
    $n = @([System.IO.File]::ReadAllLines($keysPath, [System.Text.Encoding]::UTF8) |
          Where-Object { $_.Length -gt 0 }).Count
    if ($n -eq $ExpectedDict) {
        Write-Ok "keys.txt  ($n 行，与 rec 输出维度 $ExpectedClasses 一致)"
        $needKeys = $false
    } else {
        Write-Warn2 "keys.txt  存在但行数 $n != $ExpectedDict"
    }
} else { Write-Warn2 'keys.txt  缺失' }

if ($Force) { $needDet = $true; $needRec = $true; $needKeys = $true }

Write-Host ('-' * 62) -ForegroundColor DarkGray
if (-not $needDet -and -not $needRec -and -not $needKeys) {
    Write-Ok '模型与字典齐备且校验通过。'
    Write-Host '  RESULT: PASS'
    Write-Host ''
    exit 0
}

if ($Mode -eq 'check') {
    Write-Warn2 '有文件缺失或校验不通过。运行 -Mode fetch 下载。'
    Write-Note  '注意：缺模型不会导致编译失败 —— 运行时会自动回退标准识别（ML Kit）。'
    Write-Host '  RESULT: MISSING'
    Write-Host ''
    exit 1
}

# ── fetch ────────────────────────────────────────────────────
if (-not (Test-Path $assetDir)) {
    New-Item -ItemType Directory -Path $assetDir -Force | Out-Null
    Write-Note "已创建 $assetDir"
}
if (Test-Path $workDir) { Remove-Item $workDir -Recurse -Force }
New-Item -ItemType Directory -Path $workDir -Force | Out-Null

function Get-ModelFile([string]$repo, [string]$file, [string]$dest) {
    $url = "$MsBase/$repo/repo?Revision=master&FilePath=$file"
    Write-Note "下载 $repo/$file"
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    } catch {
        Write-Err "下载失败：$($_.Exception.Message)"
        Write-Note  '若网络不通，可手动从 ModelScope 仓库页下载后放进 assets/ppocr/。'
        return $false
    }
    $mb = [Math]::Round((Get-Item $dest).Length / 1MB, 2)
    Write-Ok "已下载 $mb MB -> $dest"
    return $true
}

$fail = $false

if ($needDet) {
    if (Get-ModelFile $DetRepo 'inference.onnx' $detPath) {
        $s = Get-Sha256 $detPath
        if ($s -eq $DetSha) { Write-Ok 'det.onnx  sha256 校验通过' }
        else {
            Write-Err "det.onnx  sha256 不匹配：期望 $DetSha / 实际 $s"
            Remove-Item -LiteralPath $detPath -Force -ErrorAction SilentlyContinue
            $fail = $true
        }
    } else { $fail = $true }
}

if ($needRec) {
    if (Get-ModelFile $RecRepo 'inference.onnx' $recPath) {
        $s = Get-Sha256 $recPath
        if ($s -eq $RecSha) { Write-Ok 'rec.onnx  sha256 校验通过' }
        else {
            Write-Err "rec.onnx  sha256 不匹配：期望 $RecSha / 实际 $s"
            Remove-Item -LiteralPath $recPath -Force -ErrorAction SilentlyContinue
            $fail = $true
        }
    } else { $fail = $true }
}

# ── 生成 keys.txt ───────────────────────────────────────────
if ($needKeys -and -not $fail) {
    $yml = Join-Path $workDir 'rec_inference.yml'
    Write-Note '取 rec 的 inference.yml（字典在里面）'
    if (Get-ModelFile $RecRepo 'inference.yml' $yml) {
        $lines = [System.IO.File]::ReadAllLines($yml, [System.Text.Encoding]::UTF8)
        $start = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match 'character_dict') { $start = $i + 1; break }
        }
        if ($start -lt 0) {
            Write-Err 'yml 里找不到 character_dict'
            $fail = $true
        } else {
            $chars = New-Object System.Collections.Generic.List[string]
            for ($i = $start; $i -lt $lines.Count; $i++) {
                $l = $lines[$i]
                if (-not $l.StartsWith('  - ')) { break }
                # ⚠️ 只用 Substring，绝不能 Trim()：
                #    第 1748 条是 U+3000 全角空格，Trim() 会把它读成空串。
                $v = $l.Substring(4)
                if ($v.Length -ge 2 -and $v[0] -eq $v[$v.Length - 1] -and ($v[0] -eq "'" -or $v[0] -eq '"')) {
                    $v = $v.Substring(1, $v.Length - 2).Replace("''", "'")
                }
                [void]$chars.Add($v)
            }
            Write-Note "解析出 $($chars.Count) 个字典字符"

            $empties = @($chars | Where-Object { $_.Length -eq 0 }).Count
            if ($empties -gt 0) {
                Write-Err "字典里有 $empties 个空串条目 —— 会让下标整体错位，拒绝生成。"
                $fail = $true
            } elseif ($chars.Count -ne $ExpectedDict) {
                Write-Err "字典条目 $($chars.Count) != 期望 $ExpectedDict"
                $fail = $true
            } else {
                # 必须无 BOM：BOM 会污染第一个字符
                $enc = New-Object System.Text.UTF8Encoding($false)
                [System.IO.File]::WriteAllLines($keysPath, $chars, $enc)
                $back = @([System.IO.File]::ReadAllLines($keysPath, [System.Text.Encoding]::UTF8)).Count
                if ($back -ne $ExpectedDict) {
                    Write-Err "回读 $back 行 != $ExpectedDict"
                    $fail = $true
                } else {
                    Write-Ok "keys.txt  已写出 $back 行（无 BOM UTF-8）"
                    Write-Note "布局：1 blank + $back 字典 + 1 空格 = $($back + 2) == rec 输出维度 $ExpectedClasses"
                }
            }
        }
    } else { $fail = $true }
}

Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ('-' * 62) -ForegroundColor DarkGray
if ($fail) {
    Write-Err '未能备齐全部文件。缺模型不会导致编译失败，运行时会回退 ML Kit。'
    Write-Host '  RESULT: FAIL'
    Write-Host ''
    exit 1
}

Write-Ok '模型与字典齐备。下次构建会把它们打进 APK。'
Write-Note "体积代价参考：det 9.4 MB + rec 20.2 MB + ONNX Runtime so 17.5 MB。"
Write-Host '  RESULT: PASS'
Write-Host ''
exit 0
