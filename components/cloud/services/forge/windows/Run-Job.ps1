# Runs as the fresh, non-administrator desktop user. This file is immutable
# to that user; all mutable state belongs to the VM's disposable job disk.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal $Identity
if ($Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Actions must not run as administrator' }
if ([Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) { throw 'An interactive desktop session is required' }
$env:RUNNER_TOOL_CACHE = 'C:\ForgeJob\toolcache'
$env:FORGE_NATIVE_PLATFORM = 'windows-x86_64'
Set-Location 'C:\ForgeJob'
@'
log:
  level: info
runner:
  capacity: 1
  timeout: 2h
  insecure: false
cache:
  enabled: false
container:
  docker_host: "-"
host:
  workdir_parent: C:/ForgeJob/work
'@ | Set-Content -Encoding utf8 'C:\ForgeJob\runner.yaml'
$Uuid = [IO.File]::ReadAllText('C:\ForgeJob\uuid')
$Handle = [IO.File]::ReadAllText('C:\ForgeJob\handle')
try {
    & 'C:\Forge\forgejo-runner.exe' --config 'C:\ForgeJob\runner.yaml' one-job --handle $Handle --url 'https://git.fahrican.com' --uuid $Uuid --token-url 'file:///C:/ForgeJob/token' --label 'windows-x86_64:host' --label 'windows:host' *> 'C:\ForgeJob\runner.log'
    $Code = $LASTEXITCODE
    @{ exit_code = $Code; finished_at = (Get-Date).ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content 'C:\ForgeJob\result.json'
    exit $Code
} finally {
    Remove-Item 'C:\ForgeJob\token' -Force -ErrorAction SilentlyContinue
    # Desktop users can shut down their own VM. The broker observes SHUTOFF
    # and destroys its disposable disk; it also enforces an external deadline.
    & 'C:\Windows\System32\shutdown.exe' /s /t 30
}
