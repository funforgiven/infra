# Gorgonzola

GMKtec K8 Plus on Burrata port `1.1`; wired Omada port 3, trusted VLAN 10.
Run `configure-gorgonzola.ps1` as the local `funforgiven` administrator to apply
always-on balanced power and privacy settings; `-VerifyOnly` checks them.
Previous values and verification records go to `C:\ProgramData\infra\gorgonzola`.
Wi-Fi is disabled. The script leaves Defender local/cloud protection, sample
submission and diagnostic services unchanged. Windows Update stays enabled.
Optional diagnostics are disabled; Windows Pro still permits required diagnostics.

Install stable WSL2 with `wsl --install --no-distribution --web-download`, restart,
then install Ubuntu LTS with `wsl --install -d Ubuntu --web-download`.
The installed instance is Ubuntu 26.04.1 LTS with local user `funforgiven`.
Windows credentials and recovery answers are under `windows`, and the separate
Ubuntu credentials under `wsl`, in SOPS-encrypted
[`secrets/windows-gorgonzola.yaml`](../../../secrets/windows-gorgonzola.yaml).
Ubuntu's optional platform metrics are declined during first-run setup.
WSL services need a startup mechanism to run after Windows boots;
disabling sleep alone does not start Linux services at boot.

Run `prepare-workspace.ps1` with `prepare-ubuntu.sh` and the flake's current
wallpaper input named `wallpaper.png` beside it. It installs native Git and
Ubuntu's Nix daemon, prepares `/home/funforgiven/dev/infra`, and verifies the
repository's pinned development shell. Windows workspace instructions live in
`C:\Users\funforgiven\dev\AGENTS.md`; use `wsl.exe -d Ubuntu --cd
/home/funforgiven/dev/infra --exec bash -lc '<command>'` for Linux work.
The ChatGPT project `gorgonzola` attaches this Windows `dev` folder. Its agent
stays native to Windows for desktop control.

`prepare-workspace.ps1 -OpenAutologon` opens Microsoft's signature-checked
Sysinternals utility. Enter the local account password in its masked
field to enable automatic sign-in. It stores an encrypted LSA secret, which
administrators can recover; no plaintext registry password is needed. Verify
sign-in and ChatGPT startup with a reboot.
Windows and WSL data are disposable; no backups are configured.

ChatGPT desktop opens at Windows sign-in through the user's `ChatGPT.lnk`
Startup shortcut. After signing in, select **ChatGPT** in the top-left workspace
selector, then connect the dot from its profile under
**Computers > Your computer > Allow access**. Keep the app running for
local access; see the [connection guide](https://learn.chatgpt.com/docs/dots/computers-and-apps#connect-your-computer).
In ChatGPT **Work**, select **Plugins > Computer Use** from the composer to use
desktop apps on this computer. Calculator is the only saved app approval. Review other app approvals
in **Settings > Computer use**. On Windows, desktop tasks use the active,
unlocked session; see [Computer Use](https://learn.chatgpt.com/docs/computer-use).

Microsoft references: [privacy controls](https://learn.microsoft.com/en-us/windows/privacy/manage-connections-from-windows-operating-system-components-to-microsoft-services),
[Pro diagnostic-data minimum](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-system#allowtelemetry),
[app privacy](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-privacy),
[Windows AI](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-windowsai),
[Edge policies](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies),
[WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
