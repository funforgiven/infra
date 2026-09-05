# Run in Windows 11 Pro as an administrator after creating a standard ci user.
# Jobs run in that user's interactive desktop, never as LocalSystem/admin.
# The token is supplied as a root-only file and moved into ci's private profile.
#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)][string]$TokenFile,
    [string]$RunnerUser = 'ci'
)
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
if ($os.ProductType -ne 1 -or $os.Caption -notmatch 'Windows 11 Pro') {
    throw 'This runner requires Windows 11 Pro desktop.'
}
$account = Get-LocalUser -Name $RunnerUser
$admins = Get-LocalGroupMember -SID 'S-1-5-32-544'
if ($admins.SID.Value -contains $account.SID.Value) {
    throw 'The CI account must not be an administrator.'
}
$token = (Get-Content -Raw -LiteralPath $TokenFile).Trim()
if ($token -notmatch '^glrt-[A-Za-z0-9_.-]+$') { throw 'Invalid runner token' }
$root = 'C:\GitLab-Runner'
$state = "C:\Users\$RunnerUser\AppData\Local\GitLab-Runner"
New-Item -ItemType Directory -Force -Path $root, $state, "$state\builds" | Out-Null
$sid = $account.SID.Value
& icacls $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to secure runner installation' }
& icacls $state /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*${sid}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Failed to secure runner state' }
$binary = "$root\gitlab-runner.exe"
Invoke-WebRequest -Uri 'https://gitlab-runner-downloads.s3.amazonaws.com/v19.3.1/binaries/gitlab-runner-windows-amd64.exe' -OutFile "$binary.next"
$expected = '12e27f26a6bbb80b9dcafbf89a64618c5050b67c0a5966f4180bb7e9035f6d9f'
if ((Get-FileHash "$binary.next" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    Remove-Item "$binary.next"
    throw 'Runner checksum mismatch'
}
Move-Item -Force "$binary.next" $binary
@"
concurrent = 1
check_interval = 3
shutdown_timeout = 1800
[[runners]]
  name = "windows-11-desktop"
  url = "https://gitlab.fahrican.com"
  token = "$token"
  executor = "shell"
  shell = "powershell"
  limit = 1
  output_limit = 16384
  builds_dir = '$state\builds'
"@ | Set-Content -LiteralPath "$state\config.toml" -Encoding utf8
$token = $null
$action = New-ScheduledTaskAction -Execute $binary -Argument "run --config `"$state\config.toml`" --working-directory `"$state`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account.SID.Value
$principal = New-ScheduledTaskPrincipal -UserId $account.SID.Value -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName 'GitLab desktop runner' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
# Keep Windows Update, Defender, Secure Boot, TPM and UAC enabled.
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
Write-Output 'Installed Windows 11 desktop runner. Sign in as ci and qualify a protected-branch game test.'
