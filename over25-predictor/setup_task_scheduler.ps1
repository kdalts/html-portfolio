<#
Registers the Over 2.5 Predictor as a daily Windows Task Scheduler job.

Run this from an elevated PowerShell prompt (Run as Administrator), from
inside the over25-predictor folder:

    powershell -ExecutionPolicy Bypass -File setup_task_scheduler.ps1

It creates a task called "Over 2.5 Predictor" that runs
run_over25_predictor.bat every day at 07:00 (local time), matching the
guidance in README.md (early morning UK time, after most overnight team
news/injury updates but well before typical kick-offs).

Change $TaskTime below if you'd rather run it at a different time.
#>

$TaskName = "Over 2.5 Predictor"
$TaskTime = "07:00"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $ScriptDir "run_over25_predictor.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "Could not find run_over25_predictor.bat next to this script. Aborting."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $TaskTime
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily Over 2.5 Goals fixture scan and email (Over 2.5 Predictor)." `
    -Force

Write-Host "Registered scheduled task '$TaskName' to run daily at $TaskTime."
Write-Host "You can inspect/edit it in Task Scheduler, or test it now with:"
Write-Host "    Start-ScheduledTask -TaskName `"$TaskName`""
