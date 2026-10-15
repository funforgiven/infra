# Gorgonzola

GMKtec K8 Plus on Burrata port `1.1`; wired Omada port 3, trusted VLAN 10.
Run `configure-gorgonzola.ps1` as the local `funforgiven` administrator to apply
always-on balanced power and privacy settings; `-VerifyOnly` checks them.
Original values and verification records go to `C:\ProgramData\infra\gorgonzola`.
Wi-Fi remains disabled. Defender local/cloud protection, sample submission and
diagnostic services retain their existing configuration. Windows Update stays enabled.
Optional diagnostics are disabled; Windows Pro still permits required diagnostics.

Install stable WSL2 with `wsl --install --no-distribution --web-download`, restart,
then install Ubuntu LTS with `wsl --install -d Ubuntu --web-download`.
The installed instance is Ubuntu 26.04.1 LTS with local user `funforgiven`.
Windows credentials and recovery answers are under `windows`, and the separate
Ubuntu credentials under `wsl`, in SOPS-encrypted
[`secrets/windows-gorgonzola.yaml`](../../../secrets/windows-gorgonzola.yaml).
Ubuntu's optional platform metrics are declined during first-run setup.
WSL services need an explicit startup mechanism to run after Windows boots;
disabling sleep alone does not start Linux services at boot.

ChatGPT desktop opens at Windows sign-in through the user's `ChatGPT.lnk`
Startup shortcut. After signing in to ChatGPT, connect the dot from its profile
under **Computers > Your computer > Allow access**. Keep the app running for
local access; see the [connection guide](https://learn.chatgpt.com/docs/dots/computers-and-apps#connect-your-computer).

Microsoft references: [privacy controls](https://learn.microsoft.com/en-us/windows/privacy/manage-connections-from-windows-operating-system-components-to-microsoft-services),
[Pro diagnostic-data minimum](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-system#allowtelemetry),
[app privacy](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-privacy),
[Windows AI](https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-windowsai),
[Edge policies](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies),
[WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
