# Invoked by config-drive user data as SYSTEM on a fresh generalized VM.
param([Parameter(Mandatory=$true)][string]$EnrollmentBase64)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Enrollment = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($EnrollmentBase64)) | ConvertFrom-Json
foreach ($Name in @('uuid','token','handle')) {
    $Value = $Enrollment.$Name
    if ($Value -isnot [string] -or $Value.Length -lt 1 -or $Value.Length -gt 4096 -or $Value -match '[\x00-\x20]') {
        throw "Invalid ephemeral enrollment field: $Name"
    }
}
if (Test-Path 'C:\ForgeJob') { throw 'Refusing to reuse a previous job workspace' }
if (Get-LocalUser -Name 'forge-job' -ErrorAction SilentlyContinue) { throw 'Refusing to reuse a previous job account' }
if (-not (Confirm-SecureBootUEFI) -or -not (Get-Tpm).TpmPresent) { throw 'Required VM security features are absent' }
$Bytes = New-Object byte[] 36
$Random = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $Random.GetBytes($Bytes) } finally { $Random.Dispose() }
$Password = 'Fj1!' + [Convert]::ToBase64String($Bytes)
$SecurePassword = ConvertTo-SecureString $Password -AsPlainText -Force
$User = New-LocalUser -Name 'forge-job' -Password $SecurePassword -AccountNeverExpires -PasswordNeverExpires -UserMayNotChangePassword -Description 'Disposable non-administrator Actions desktop'
$UsersGroup = (Get-LocalGroup -SID 'S-1-5-32-545').Name
Add-LocalGroupMember -Group $UsersGroup -Member $User
New-Item -ItemType Directory 'C:\ForgeJob' | Out-Null
& icacls.exe 'C:\ForgeJob' /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' ('*' + $User.SID.Value + ':(OI)(CI)F') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot isolate job directory' }
foreach ($Name in @('uuid','token','handle')) { [IO.File]::WriteAllText(('C:\ForgeJob\' + $Name), $Enrollment.$Name) }
# The password is unique to this VM and is stored by Microsoft's signed tool
# as an LSA secret. The task runs in the interactive desktop, without elevation.
& 'C:\Forge\autologon\Autologon64.exe' 'forge-job' $env:COMPUTERNAME $Password /accepteula
if ($LASTEXITCODE -ne 0) { throw 'Cannot configure the disposable desktop logon' }
$Password = $null
$Action = New-ScheduledTaskAction -Execute 'C:\Program Files\PowerShell\7\pwsh.exe' -Argument '-NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\Forge\Run-Job.ps1' -WorkingDirectory 'C:\ForgeJob'
$Principal = New-ScheduledTaskPrincipal -UserId ($env:COMPUTERNAME + '\forge-job') -LogonType Interactive -RunLevel Limited
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User ($env:COMPUTERNAME + '\forge-job')
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'ForgeDisposableJob' -Action $Action -Principal $Principal -Trigger $Trigger -Settings $Settings | Out-Null
# The external broker also expires the VM. This local watchdog survives a
# disconnected broker and never runs commands from the writable job directory.
$Shutdown = New-ScheduledTaskAction -Execute 'C:\Windows\System32\shutdown.exe' -Argument '/s /f /t 0'
$Expiry = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(135)
Register-ScheduledTask -TaskName 'ForgeJobExpiry' -Action $Shutdown -Trigger $Expiry -User 'SYSTEM' -RunLevel Highest | Out-Null
Write-Output 'Prepared a fresh unprivileged interactive job; only its ephemeral identity is present.'
# Cloudbase-Init records completion and reboots once into the new desktop.
exit 1001
