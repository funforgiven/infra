# Seal only this task's dedicated image builder after updates and validation.
param([switch]$Schedule)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Schedule) {
    if ($env:COMPUTERNAME -ne 'FORGE-WIN-BUILD') { throw 'This is not the dedicated image builder' }
    $Checkpoint = Get-Content 'C:\Forge\preseal-checkpoint.json' -Raw | ConvertFrom-Json
    if ($Checkpoint.status -ne 'available' -or $Checkpoint.builder_name -ne 'forge-windows-image-builder') {
        throw 'A verified recovery snapshot is required before preparing to seal'
    }
    $Action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Forge\Seal.ps1'
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName 'ForgeImageSeal' -Action $Action -Principal $Principal -Settings $Settings -Trigger (New-ScheduledTaskTrigger -AtStartup) -Force | Out-Null
    # SSH loads the administrator profile even without an interactive session.
    # Seal on a clean boot, with that account unable to log in again.
    Disable-LocalUser -Name 'forge-builder'
    Set-Service sshd -StartupType Disabled
    & shutdown.exe /r /t 10 /d p:2:4 /c 'Prepare the dedicated Forgejo runner image for sealing'
    Write-Output 'Scheduled image sealing after a clean reboot; the temporary builder account is disabled.'
    exit 0
}
Start-Transcript -Path 'C:\Forge\seal.log' -Append
try {
    if ($env:COMPUTERNAME -ne 'FORGE-WIN-BUILD') { throw 'This is not the dedicated image builder' }
    $Builder = Get-LocalUser -Name 'forge-builder'
    $Checkpoint = Get-Content 'C:\Forge\preseal-checkpoint.json' -Raw | ConvertFrom-Json
    if ($Checkpoint.status -ne 'available' -or $Checkpoint.builder_name -ne 'forge-windows-image-builder') {
        throw 'An authenticated, available pre-seal recovery snapshot is required'
    }
    if ((Get-ScheduledTask -TaskName 'ForgeImageUpdates').State -eq 'Running') { throw 'Updates are still running' }
    $Updates = Get-Content 'C:\Forge\updates.json' -Raw | ConvertFrom-Json
    if ($Updates.installed_count -ne 0 -or $Updates.reboot_required) { throw 'Reboot and rescan Windows Update until no required updates remain' }
    foreach ($Pending in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')) {
        if (Test-Path $Pending) { throw 'Windows requires a reboot before sealing' }
    }
    if (-not (Confirm-SecureBootUEFI) -or -not (Get-Tpm).TpmPresent) { throw 'Secure Boot and TPM are required' }
    if ((Get-BitLockerVolume -MountPoint 'C:').VolumeStatus -ne 'FullyDecrypted') { throw 'A golden image must not depend on this builder vTPM' }
    $Broken = @(Get-CimInstance Win32_PnPEntity | Where-Object ConfigManagerErrorCode -ne 0)
    if ($Broken.Count) { throw 'Resolve all device driver errors before sealing' }
    foreach ($File in @('Start-Job.ps1','Run-Job.ps1','forgejo-runner.exe','autologon\Autologon64.exe','cloudbase-init.conf','cloudbase-init-unattend.conf','provisioned.json')) {
        if (-not (Test-Path ('C:\Forge\'+$File))) { throw ('Missing image input: '+$File) }
    }
    if ((Get-FileHash 'C:\Forge\forgejo-runner.exe').Hash.ToLowerInvariant() -ne 'cf2ae0bf1245b4d1fbff3a987c2544afa4e20807f2d70d47e59db4da84809fb4') { throw 'Runner binary differs from the reproducible build' }
    $Cloudbase = 'C:\Program Files\Cloudbase Solutions\Cloudbase-Init'
    Stop-Service cloudbase-init -ErrorAction SilentlyContinue
    Copy-Item 'C:\Forge\cloudbase-init.conf','C:\Forge\cloudbase-init-unattend.conf' "$Cloudbase\conf\" -Force
    Remove-Item 'HKLM:\SOFTWARE\Cloudbase Solutions\Cloudbase-Init' -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem "$Cloudbase\log" -File | Remove-Item -Force
    Set-Service cloudbase-init -StartupType Automatic
    # A clone obtains only one ephemeral job identity from its local ISO config
    # drive. It has no persistent remote administrator or reusable host key.
    Stop-Service sshd
    Set-Service sshd -StartupType Disabled
    Get-ChildItem 'C:\ProgramData\ssh\ssh_host_*','C:\ProgramData\ssh\administrators_authorized_keys' -ErrorAction SilentlyContinue | Remove-Item -Force
    Disable-LocalUser -Name 'forge-builder'
    $RandomPassword = ConvertTo-SecureString ([Guid]::NewGuid().ToString('N') + [Guid]::NewGuid().ToString('N') + '!a1') -AsPlainText -Force
    Set-LocalUser -Name 'forge-builder' -Password $RandomPassword
    $Winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Set-ItemProperty $Winlogon AutoAdminLogon '0'
    foreach ($Name in @('DefaultPassword','DefaultUserName','DefaultDomainName','AutoLogonCount')) {
        Remove-ItemProperty $Winlogon $Name -ErrorAction SilentlyContinue
    }
    $Sessions = @(Get-Process -IncludeUserName | Where-Object { $_.UserName -like '*\forge-builder' -and $_.SessionId -gt 0 } | Select-Object -ExpandProperty SessionId -Unique)
    foreach ($Session in $Sessions) { & logoff.exe $Session }
    Start-Sleep -Seconds 5
    $Profile = Get-CimInstance Win32_UserProfile | Where-Object SID -eq $Builder.SID.Value
    if ($Profile) {
        if ($Profile.Loaded) { throw 'Builder profile is still loaded' }
        $Profile | Remove-CimInstance
    }
    Remove-LocalUser -Name 'forge-builder'
    Get-ChildItem 'C:\Windows\Panther' -Filter '*unattend*.xml' -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force
    foreach ($Path in @('C:\Forge\tools','C:\Forge\fwcfg','C:\Forge\operator.pub','C:\Forge\provision-error.txt','C:\Forge\provision.log')) {
        Remove-Item $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
    Unregister-ScheduledTask -TaskName 'ForgeImageUpdates' -Confirm:$false
    Unregister-ScheduledTask -TaskName 'ForgeImageSeal' -Confirm:$false
    # Root-owned scripts and tools stay read-only to the eventual job user.
    & icacls.exe 'C:\Forge' /inheritance:r /grant '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot secure the sealed image tools' }
    @{
        sealed_at = (Get-Date).ToUniversalTime().ToString('o')
        build = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
        revision = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').UBR
        secure_boot = Confirm-SecureBootUEFI
        tpm_version = (Get-CimInstance -Namespace root/cimv2/security/microsofttpm -Class Win32_Tpm).SpecVersion
        config_drive_only = $true
        builder_account_removed = $true
    } | ConvertTo-Json | Set-Content 'C:\Forge\sealed.json'
    # Sysprep's parser is not the normal Windows argv parser; keep its answer
    # file path free of spaces and nested quoting.
    Copy-Item "$Cloudbase\conf\Unattend.xml" 'C:\Forge\Sysprep.xml' -Force
    $Process = Start-Process 'C:\Windows\System32\Sysprep\Sysprep.exe' -ArgumentList '/generalize /oobe /shutdown /quiet /unattend:C:\Forge\Sysprep.xml' -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw ('Sysprep failed: '+$Process.ExitCode) }
    if (-not (Test-Path 'C:\Windows\System32\Sysprep\Sysprep_succeeded.tag')) { throw 'Sysprep did not complete; do not promote this image' }
} catch {
    $_ | Out-String | Set-Content 'C:\Forge\seal-error.txt'
    throw
} finally { Stop-Transcript }
