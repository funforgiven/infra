# Apply Windows-serviced software updates before sealing the golden image.
param([switch]$Schedule)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Schedule) {
    # Windows Update's COM downloader rejects SSH impersonation contexts.
    # Use a bounded local SYSTEM task, without changing remote access policy.
    $Existing = Get-ScheduledTask -TaskName 'ForgeImageUpdates' -ErrorAction SilentlyContinue
    if ($Existing -and $Existing.State -eq 'Running') { throw 'Image updates are already running' }
    $Action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Forge\Update.ps1'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName 'ForgeImageUpdates' -Action $Action -Principal $Principal -Settings $Settings -Force | Out-Null
    Start-ScheduledTask -TaskName 'ForgeImageUpdates'
    Write-Output 'Started bounded Windows Update task in the local system context.'
    exit 0
}
Start-Transcript -Path 'C:\Forge\updates.log' -Append
try {
    $Session = New-Object -ComObject Microsoft.Update.Session
    $Session.ClientApplicationID = 'Forge Windows image qualification'
    $Search = $Session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
    $Updates = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($Update in $Search.Updates) {
        if ($Update.BrowseOnly) { continue }
        if (-not $Update.EulaAccepted) { $Update.AcceptEula() }
        [void]$Updates.Add($Update)
        Write-Output ('Selected update: ' + $Update.Title)
    }
    $Reboot = $false
    if ($Updates.Count -gt 0) {
        $Downloader = $Session.CreateUpdateDownloader()
        $Downloader.Updates = $Updates
        $Download = $Downloader.Download()
        if ($Download.ResultCode -ne 2) { throw "Windows Update download failed: $($Download.ResultCode)" }
        $Installer = $Session.CreateUpdateInstaller()
        $Installer.Updates = $Updates
        $Installer.ForceQuiet = $true
        $Result = $Installer.Install()
        if ($Result.ResultCode -ne 2) { throw "Windows Update installation failed: $($Result.ResultCode)" }
        $Reboot = $Result.RebootRequired
    }
    @{
        completed_at = (Get-Date).ToUniversalTime().ToString('o')
        installed_count = $Updates.Count
        reboot_required = $Reboot
        build = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
        revision = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR
    } | ConvertTo-Json | Set-Content 'C:\Forge\updates.json'
} finally { Stop-Transcript }
