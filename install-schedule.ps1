<#
.SYNOPSIS
    Registers (or removes) a Windows scheduled task that runs daily.py once a day.

.DESCRIPTION
    Runs every day at -At (default 9:00 AM). If the PC is off or asleep then,
    Windows runs it as soon as it can.

    LeetCode publishes the new challenge at 00:00 UTC (7 PM EST / 8 PM EDT), so a
    run during the day gets that day's problem and a run after that gets the next one.

    The task runs as you, only while you're logged on, with no admin rights needed.
    It uses pythonw.exe, so no console window pops up.

.EXAMPLE
    .\install-schedule.ps1                    # every day at 9:00 AM, python3 starter code
    .\install-schedule.ps1 -At 07:30          # a different time (24-hour clock)
    .\install-schedule.ps1 -Lang python3,cpp  # several languages
    .\install-schedule.ps1 -Uninstall
#>
param(
    [string]$At = "09:00",
    [string[]]$Lang = @("python3"),
    [switch]$Uninstall
)
$ErrorActionPreference = "Stop"
$TaskName = "LeetCode Daily Download"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "No scheduled task named '$TaskName' found."
    }
    return
}

$script = Join-Path $PSScriptRoot "daily.py"
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw "pythonw.exe not found on PATH. Install Python 3.8+ first." }
$langArg = ($Lang -join ",") -replace '[^a-z0-9,]', ''

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$script`" --lang $langArg" -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]$At)
# PowerShell stores the start as UTC ("...Z"), which drifts an hour with daylight
# saving. A time with no zone means local wall-clock time, so 9:00 stays 9:00.
$trigger.StartBoundary = ([datetime]$At).ToString("yyyy-MM-dd'T'HH:mm:ss")

# StartWhenAvailable: if the PC was off or asleep at $At, run as soon as it's back.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "Downloads the LeetCode daily challenge into $PSScriptRoot\problems (see daily.py)." | Out-Null

Write-Host "Registered '$TaskName': runs daily at $(([datetime]$At).ToString('h:mm tt')), starter code: $langArg"
Write-Host "Output: $PSScriptRoot\problems   Log: $PSScriptRoot\daily.log"
Write-Host "Remove it with: .\install-schedule.ps1 -Uninstall"
