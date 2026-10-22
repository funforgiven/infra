#Requires -RunAsAdministrator
[CmdletBinding()]
param([switch]$OpenAutologon)

$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'GORGONZOLA' -or $env:USERNAME -ne 'funforgiven') {
    throw 'Run as the local funforgiven administrator on GORGONZOLA.'
}
$bootstrap = 'C:\ProgramData\infra\gorgonzola\bootstrap'
New-Item -ItemType Directory -Force $bootstrap | Out-Null
foreach ($name in @('prepare-ubuntu.sh', 'wallpaper.png')) {
    $source = Join-Path $PSScriptRoot $name
    $destination = Join-Path $bootstrap $name
    if ($source -ne $destination) { Copy-Item -LiteralPath $source -Destination $destination -Force }
}

if (-not (Test-Path 'C:\Program Files\Git\cmd\git.exe')) {
    winget.exe install --id Git.Git --exact --source winget --silent `
        --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Git installation failed: $LASTEXITCODE" }
}
& 'C:\Program Files\Git\cmd\git.exe' config --global core.autocrlf input
& 'C:\Program Files\Git\cmd\git.exe' config --global init.defaultBranch main

$linuxBootstrap = '/mnt/c/ProgramData/infra/gorgonzola/bootstrap'
wsl.exe -d Ubuntu -u root --exec bash "$linuxBootstrap/prepare-ubuntu.sh"
if ($LASTEXITCODE -ne 0) { throw 'Ubuntu workspace preparation failed.' }

$workspace = Join-Path $env:USERPROFILE 'dev'
New-Item -ItemType Directory -Force $workspace | Out-Null
@'
Use PowerShell for Windows tasks. The Linux infrastructure checkout is /home/funforgiven/dev/infra in Ubuntu.
Run Linux commands with wsl.exe -d Ubuntu --cd /home/funforgiven/dev/infra --exec bash -lc '<command>'.
Enter nix develop --accept-flake-config there for the repository's pinned tools. Use Conventional Commits.
'@ | Set-Content -Encoding UTF8 (Join-Path $workspace 'AGENTS.md')
Write-Host 'Windows workspace and Ubuntu infrastructure checkout are ready.'
if ($OpenAutologon) {
    # Sysinternals publishes no stable hash for this rolling download, so the
    # Authenticode chain is the integrity check.
    $tools = Join-Path $env:LOCALAPPDATA 'infra\autologon'
    New-Item -ItemType Directory -Force $tools | Out-Null
    curl.exe --fail --location --output "$tools\Autologon.zip" https://download.sysinternals.com/files/AutoLogon.zip
    if ($LASTEXITCODE -ne 0) { throw 'Autologon download failed.' }
    Expand-Archive -LiteralPath "$tools\Autologon.zip" -DestinationPath $tools -Force
    $autologon = Join-Path $tools 'Autologon64.exe'
    $signature = Get-AuthenticodeSignature -LiteralPath $autologon
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        throw 'Autologon must have a valid Microsoft signature.'
    }
    # Enter the account password only in the masked GUI field.
    Start-Process -FilePath $autologon
}
