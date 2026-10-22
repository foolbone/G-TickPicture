<#
.SYNOPSIS
  Run a command OUTSIDE the WorkBuddy sandbox process tree.

.DESCRIPTION
  Why this exists:
    Every command launched from the agent Bash/PowerShell tool runs inside
    sandbox-cli.exe (process chain: pwsh -> sandbox-cli -> WorkBuddy).
    That sandbox isolates the Windows named-pipe object namespace, so any
    Dart VM child-process spawn that needs stdio pipes fails with:
        CreateFile failed 231 / "ERROR_PIPE_BUSY"
    Because the whole Flutter toolchain is a Dart program that spawns
    subprocesses (git, adb, java, pub), EVERY flutter command dies there.

    Scheduled Tasks are started by the Task Scheduler service (svchost),
    NOT from our process tree, so they run unsandboxed. This script uses
    that as an escape hatch.

  IMPORTANT: a human running PowerShell normally is NOT sandboxed.
    `flutter doctor` works fine from a normal terminal. This script is
    only needed when driving the toolchain from inside the agent session.

  2026-09-23 REDESIGN (after real-world failures):
    1) NO wrapper .cmd file. The sandbox CoW-shadowed wrapper files, so
       the task sometimes could not see what the agent wrote. The task
       action is an INLINE powershell.exe command string.
    2) NO Invoke-Expression with embedded double quotes. Passing `\"`
       through powershell.exe -Command silently broke in PS 5.1 (task ran,
       exit 0, but the inner command never executed). The -Command string
       is built WITHOUT any double quotes: the Command parameter is
       parsed as '"<exe>" <args>' and replayed with the call operator:
           & '<exe>' <args> *>> '<OutFile>'
    3) The `.done` marker proved UNRELIABLE (task-written, invisible to
       the sandbox). Completion is detected by polling the OutFile until
       its size is stable for 2 consecutive checks (20s); the marker is
       kept as a cheap secondary signal.
    4) OutFile lives in %TEMP% (verified transparent across the sandbox
       boundary: task writes -> agent reads). Do NOT put OutFile under
       the project directory.
    5) Battery conditions: -AllowStartIfOnBatteries / -DontStopIfGoingOnBatteries.
       Without them the task stays QUEUED forever on battery power.
    6) The inner powershell does Set-Location first - without it flutter
       analyzes C:\Windows\System32 and reports a fake green.

.PARAMETER Command
  MUST be of the form '"<exe>" <args>' (exe path in double quotes),
  e.g. '"D:\dev\flutter\bin\flutter.bat" analyze'

.PARAMETER WorkingDirectory
  Optional start directory for the command.

.PARAMETER OutFile
  Where stdout+stderr are captured. Use %TEMP%.

.PARAMETER TimeoutSec
  Max wait in seconds (default 900).

.EXAMPLE
  .\tools\run_unsandboxed.ps1 -Command '"D:\dev\flutter\bin\flutter.bat" analyze' -WorkingDirectory 'D:\G-TickPicture\app'
#>
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string] $Command,

  [string] $WorkingDirectory = '',

  [string] $OutFile = "$env:TEMP\gt_run_out.txt",

  [int] $TimeoutSec = 900
)

$ErrorActionPreference = 'Stop'
$taskName = 'GtUnsandboxedRun'

function Write-Note([string] $msg) { Write-Host "  $msg" }

# --- guardrails ----------------------------------------------------------
if ($OutFile -like 'D:\G-TickPicture\*') {
  Write-Warning '  OutFile is inside the project directory - the task may write where the agent cannot read. Prefer %TEMP%.'
}

# --- parse Command: '"<exe>" <args>' --------------------------------------
$c = $Command.Trim()
if (-not $c.StartsWith('"')) {
  throw 'Command must start with a double-quoted exe path, e.g. "D:\dev\flutter\bin\flutter.bat" analyze'
}
$endIdx = $c.IndexOf('"', 1)
if ($endIdx -lt 0) { throw 'Command: unmatched opening quote for the exe path.' }
$exe     = $c.Substring(1, $endIdx - 1)
$argLine = $c.Substring($endIdx + 1).Trim()
if ($exe -like "*'*")     { throw 'Exe path must not contain single quotes.' }
if ($argLine -like "*'*") { throw 'Arguments must not contain single quotes (script convention).' }

# --- prepare -------------------------------------------------------------
$outDir = Split-Path $OutFile -Parent
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
if (Test-Path $OutFile) { Remove-Item $OutFile -Force }

$marker = "$OutFile.done"
if (Test-Path $marker) { Remove-Item $marker -Force }

# Inner powershell script text - built WITHOUT double quotes so the
# -Command "..." handoff needs no quote escaping at all.
$loc = if ($WorkingDirectory -ne '') { $WorkingDirectory } else { (Get-Location).Path }
$inner = "Set-Location -LiteralPath '$loc'; " +
         "& '$exe' $argLine *>> '$OutFile'; " +
         "'EXIT=' + `$LASTEXITCODE *>> '$OutFile'"

# --- (re)register --------------------------------------------------------
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null } catch {}

$ps        = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$action    = New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -Command "' + $inner + '"')
$trigger   = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(-1))
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromHours(2)) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Write-Host '  [run_unsandboxed] task registered (inline action, battery-exempt), launching...'
Start-ScheduledTask -TaskName $taskName

# --- wait ----------------------------------------------------------------
# Primary signal: the task appends 'EXIT=<code>' as its very last line
# (see $inner above) - poll the OutFile for it. Deterministic.
# DO NOT resurrect the size-stability + Get-ScheduledTask state heuristic:
# `flutter test` has multi-minute quiet stretches (the export stress test
# writes nothing for ~224s), and in this environment the task state reads
# back as non-'Running', so the runner broke early, read a partial file,
# and the release gate failed a run that had actually passed
# (2026-10-14, v0.21.2 release aborted on a green test suite).
# Secondary signal: .done marker (cheap; historically unreliable).
$sw = [Diagnostics.Stopwatch]::StartNew()
$completed = $false
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
  Start-Sleep -Seconds 5
  if (Test-Path $OutFile) {
    try {
      $tailLines = @(Get-Content $OutFile -Tail 5 -ErrorAction SilentlyContinue)
      if ($tailLines | Where-Object { $_ -like 'EXIT=*' }) { $completed = $true; break }
    } catch {}
  }
  if (Test-Path $marker) { $completed = $true; break }
}
$sw.Stop()

$info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
Write-Host ("  [run_unsandboxed] elapsed=" + [int]$sw.Elapsed.TotalSeconds + "s  completed=$completed  LastResult=" + $info.LastTaskResult)

# --- emit ----------------------------------------------------------------
if (Test-Path $OutFile) {
  Write-Host '----- OUTPUT -----'
  Get-Content $OutFile
  Write-Host '----- END -----'
  $tail = @(Get-Content $OutFile -Tail 8)
  $exitLine = $tail | Where-Object { $_ -like 'EXIT=*' } | Select-Object -Last 1
  if ($exitLine) {
    Write-Host "  [run_unsandboxed] $exitLine"
    if ($exitLine -eq 'EXIT=0') { exit 0 } else { exit 1 }
  }
} else {
  Write-Host '  [run_unsandboxed] NO OUTPUT FILE - the task did not write anything.'
}

# --- cleanup -------------------------------------------------------------
try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null } catch {}
if (Test-Path $marker)  { Remove-Item $marker  -Force }
