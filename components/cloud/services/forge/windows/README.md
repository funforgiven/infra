# Windows 11 desktop image

Build private Windows 11 Pro 25H2 media with `build-media.py`. It requires the
owner's Microsoft ISO, the pinned VirtIO ISO, the reproducible native Forgejo
runner, the files in `inputs.json`, and one operator Ed25519 public key. Run it
with `7zz` and `mkisofs` from the infrastructure's pinned Nix packages.

The output contains a unique temporary administrator password. Keep the work
directory private, upload the ISO only to the isolated `forge-ci` project, and
attach it only to a **new, empty 240 GiB image-builder disk**. The unattended
installer formats that disk. It preserves Microsoft's signed EFI bootloader
and requires Secure Boot and TPM 2.0; it does not bypass Windows requirements.
Windows activation remains separate from installing the desktop edition.

`Provision.ps1` verifies the guest's hardware requirements, all pinned installer
hashes and Authenticode signatures. Windows Exporter uses a self-signed
[upstream release certificate](https://github.com/prometheus-community/windows_exporter/blob/v0.31.8/installer/codesign.cer).
Its exact DER hash is pinned, its signer must match, and temporary verification
trust is removed immediately. No additional root certificate remains installed.
OpenSSH is key-only and restricted to operator LAN/WireGuard sources; its
public identity is enrolled through the authenticated Nova console, never TOFU.

The first builder has booted with Secure Boot and TPM 2.0, installed all tools,
loaded the signed VirtIO drivers with no remaining device errors, and executed
`forgejo-runner --version`. Native workflow execution and sealed-image clone
qualification are still required before promoting it for application jobs.

## Updates and sealing

Run the reviewed updater through the pinned SSH connection:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Forge\Update.ps1 -Schedule
```

It runs Windows Update locally as SYSTEM because the COM downloader does not
support the SSH impersonation context. Inspect `C:\Forge\updates.json` and the
`ForgeImageUpdates` task. Reboot when requested, then rescan until the report
has zero installed updates and no reboot pending. Optional preview updates are
excluded. Execution-policy overrides apply only to these processes.

Before sealing, stop the builder cleanly and take a private Cinder root-volume
snapshot. Verify it is `available`, record its ID, volume ID, builder name and
status in `C:\Forge\preseal-checkpoint.json`, then boot the builder again. Keep
that checkpoint until a clone passes native Actions qualification; it permits
recovery if Sysprep fails after the temporary account is removed.

Copy the reviewed job scripts and both Cloudbase configuration files into
`C:\Forge`, then run `Seal.ps1 -Schedule` with the same process-local execution
policy override. It disables the builder account and reboots once so SSH cannot
keep its profile loaded. A SYSTEM startup task then checks updates, drivers,
encryption and provenance,
removes the temporary administrator and SSH identities, restricts the installed
tools to administrator writes, and generalizes the image with Sysprep. Do not
capture a golden image until Nova reports `SHUTOFF` and sealing has succeeded.
The sealed disk must be fully decrypted so clones can use independent vTPMs.

## Disposable jobs

The external controller creates a fresh Windows VM and root volume from the
protected, revision-pinned golden image. The fixed isolated Neutron port limits
Windows concurrency to one. Cloudbase uses only an ISO config drive, with no
HTTP metadata or WinRM plugins. Its user data supplies a one-job Forgejo
identity to `Start-Job.ps1`; reusable repository or cloud credentials never
enter the guest.

Each VM creates a unique non-administrator `forge-job` account and password.
Microsoft Autologon stores the password as an LSA secret, and a scheduled task
runs `Run-Job.ps1` in the user's interactive desktop. The runner rejects an
administrator token or Session 0. The job shuts down its VM when finished, a
local watchdog expires it after 135 minutes, and the external controller also
expires and deletes its VM and disk. Qualification must verify this lifecycle,
checkout, artifacts, software rendering, and network isolation before enabling
application repositories. Atollion stays on GitHub until the owner explicitly
requests its migration.
