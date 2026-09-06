# Executed once on the private image builder, before generalizing its disk.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = 'C:\Forge'
Start-Transcript -Path "$Root\provision.log" -Append
try {
    # End the temporary installer autologon immediately. The sealed image never
    # contains this password or an enabled administrator autologon.
    $Winlogon = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
    Set-ItemProperty $Winlogon AutoLogonCount 0
    Set-ItemProperty $Winlogon AutoAdminLogon '0'
    Remove-ItemProperty $Winlogon DefaultPassword -ErrorAction SilentlyContinue
    if (-not (Confirm-SecureBootUEFI)) { throw 'Secure Boot is not enabled' }
    if (-not (Get-Tpm).TpmPresent) { throw 'A TPM is required' }
    $Tpm = Get-CimInstance -Namespace root/cimv2/security/microsofttpm -Class Win32_Tpm
    if ($Tpm.SpecVersion -notmatch '^2\.0') { throw 'TPM 2.0 is required' }
    if ((Get-ComputerInfo).WindowsProductName -notmatch 'Windows (10|11) Pro') {
        throw 'The image must be the Windows 11 Pro desktop edition'
    }
    if ([int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild -lt 26200) {
        throw 'Windows 11 25H2 or newer is required'
    }
    New-Item -ItemType Directory -Force "$Root\metrics" | Out-Null

    # Windows-serviced SSH, key-only and reachable only through operator LAN/WG.
    $Ssh = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
    if ($Ssh.State -ne 'Installed') {
        Add-WindowsCapability -Online -Name $Ssh.Name | Out-Null
    }
    New-Item -ItemType Directory -Force 'C:\ProgramData\ssh' | Out-Null
    @'
Port 22
PasswordAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
AllowUsers forge-builder
Subsystem sftp sftp-server.exe
Match Group administrators
    AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys
'@ | Set-Content -Encoding ascii 'C:\ProgramData\ssh\sshd_config'
    Copy-Item "$Root\operator.pub" 'C:\ProgramData\ssh\administrators_authorized_keys' -Force
    & icacls.exe 'C:\ProgramData\ssh\administrators_authorized_keys' /inheritance:r /grant '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot secure SSH keys' }
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue |
        Set-NetFirewallRule -Enabled True -Profile Any -RemoteAddress '10.21.10.0/24','10.21.91.0/24'
    if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'Operator SSH' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -RemoteAddress '10.21.10.0/24','10.21.91.0/24' | Out-Null
    }
    # Only the public host key is emitted to the authenticated Nova console.
    $Serial = New-Object System.IO.Ports.SerialPort COM1,115200,None,8,one
    try {
        $Serial.Open()
        $Serial.WriteLine('FORGE_HOST_KEY=' + (Get-Content 'C:\ProgramData\ssh\ssh_host_ed25519_key.pub'))
    } finally { $Serial.Dispose() }

    $Inputs = Get-Content "$Root\inputs.json" -Raw | ConvertFrom-Json
    $ExporterCertificatePath = "$Root\tools\windows-exporter-codesign.cer"
    if ((Get-FileHash $ExporterCertificatePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '1a5e0398379ab64d680a297a0a1578883ad557bd148b8076cae586c89cfd6d8b') {
        throw 'Windows Exporter signing certificate does not match the pinned upstream release'
    }
    $ExporterCertificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $ExporterCertificatePath
    foreach ($InputFile in $Inputs) {
        $Path = Join-Path "$Root\tools" $InputFile.name
        $Hash = (Get-FileHash $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ('sha256:' + $Hash -ne $InputFile.digest) { throw "Checksum mismatch: $($InputFile.name)" }
        if ($Path -match '\.(msi|exe)$') {
            $Signature = Get-AuthenticodeSignature $Path
            if ($InputFile.name -like 'windows_exporter-*.msi') {
                # Upstream uses its own signing certificate. Pin its exact DER
                # bytes and trust it only for this verification. Never leave
                # an extra trust root in the image. CurrentUser root enrollment
                # requires an interactive prompt unavailable in an SSH session.
                if ($Signature.SignerCertificate.Thumbprint -ne $ExporterCertificate.Thumbprint) {
                    throw 'Unexpected Windows Exporter signer'
                }
                $CertificateStore = New-Object System.Security.Cryptography.X509Certificates.X509Store 'Root','LocalMachine'
                $CertificateStore.Open('ReadWrite')
                try {
                    $CertificateStore.Add($ExporterCertificate)
                    $Signature = Get-AuthenticodeSignature $Path
                } finally {
                    $CertificateStore.Remove($ExporterCertificate)
                    $CertificateStore.Close()
                }
            }
            if ($Signature.Status -ne 'Valid') { throw "Invalid Authenticode signature: $($InputFile.name)" }
        }
    }
    foreach ($Name in @('PowerShell-*x64.msi','node-*-x64.msi','CloudbaseInitSetup_Stable_x64.msi','windows_exporter-*-amd64.msi')) {
        $Installer = @(Get-ChildItem "$Root\tools\$Name")
        if ($Installer.Count -ne 1) { throw "Ambiguous installer: $Name" }
        $Options = '/i "' + $Installer[0].FullName + '" /qn /norestart'
        if ($Name -like 'Cloudbase*') { $Options += ' RUN_SERVICE_AS_LOCAL_SYSTEM=1 LOGGINGSERIALPORTNAME="COM1"' }
        $Process = Start-Process msiexec.exe -ArgumentList $Options -Wait -PassThru
        if ($Process.ExitCode -notin @(0,3010)) { throw "Installer failed: $Name ($($Process.ExitCode))" }
    }
    Stop-Service cloudbase-init -ErrorAction SilentlyContinue
    Set-Service cloudbase-init -StartupType Disabled
    $GitInstaller = @(Get-ChildItem "$Root\tools\Git-*-64-bit.exe")
    if ($GitInstaller.Count -ne 1) { throw 'Ambiguous Git installer' }
    $Process = Start-Process $GitInstaller[0].FullName -ArgumentList '/VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES /o:PathOption=Cmd' -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw 'Git installer failed' }
    Expand-Archive "$Root\tools\Autologon.zip" "$Root\autologon" -Force
    if ((Get-AuthenticodeSignature "$Root\autologon\Autologon64.exe").Status -ne 'Valid') { throw 'Invalid Autologon signature' }
    New-ItemProperty 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value 'C:\Program Files\PowerShell\7\pwsh.exe' -PropertyType String -Force | Out-Null
    Get-NetFirewallPortFilter | Where-Object LocalPort -eq 9182 | Get-NetFirewallRule |
        Set-NetFirewallRule -RemoteAddress '10.21.40.154/32'
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' UserAuthentication 1
    & w32tm.exe /config '/manualpeerlist:162.159.200.1,0x8 162.159.200.123,0x8' /syncfromflags:manual /update | Out-Null
    & powercfg.exe /hibernate off
    & powercfg.exe /change standby-timeout-ac 0
    # Drivers remain subject to Secure Boot and Windows code integrity.
    $DriverErrors = @(Get-CimInstance Win32_PnPEntity | Where-Object ConfigManagerErrorCode -ne 0)
    ConvertTo-Json -InputObject @($DriverErrors | Select-Object Name,ConfigManagerErrorCode) | Set-Content "$Root\device-errors.json"
    if ($DriverErrors.Count) { throw 'Resolve missing or failing guest device drivers before promotion' }
    @{
        secure_boot = Confirm-SecureBootUEFI
        tpm_version = $Tpm.SpecVersion
        build = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuild
        runner_sha256 = (Get-FileHash "$Root\forgejo-runner.exe").Hash.ToLowerInvariant()
        provisioned_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json | Set-Content "$Root\provisioned.json"
} catch {
    $_ | Out-String | Set-Content "$Root\provision-error.txt"
    throw
} finally { Stop-Transcript }
