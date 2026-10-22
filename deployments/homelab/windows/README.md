# Gorgonzola

Windows workstation on the trusted VLAN, used as a desktop-control agent host
with a WSL2 Ubuntu checkout of this repository. Credentials (Windows under
`windows`, Ubuntu under `wsl`) are in `secrets/windows-gorgonzola.yaml`.

Run order, as the local `funforgiven` administrator:

1. `configure-gorgonzola.ps1` applies always-on power and privacy policy and
   records previous and verified values under `C:\ProgramData\infra\gorgonzola`
   (`-VerifyOnly` only checks). Defender, Windows Update and required
   diagnostics stay enabled; Pro cannot turn diagnostics fully off.
2. `wsl --install --no-distribution --web-download`, reboot, then
   `wsl --install -d Ubuntu --web-download` with local user `funforgiven`.
3. `prepare-workspace.ps1` with `prepare-ubuntu.sh` and the flake's wallpaper
   input saved as `wallpaper.png` beside it. It installs Git, Ubuntu's Nix
   daemon and the checkout, and verifies the pinned development shell.
4. `prepare-workspace.ps1 -OpenAutologon` downloads the signature-checked
   Sysinternals Autologon. The desktop agent needs an unlocked session after
   every boot; Autologon keeps the password as an LSA secret, never in plain text.

WSL services do not start at Windows boot on their own; disabling sleep does
not help. Windows and WSL data are disposable and are not backed up.
