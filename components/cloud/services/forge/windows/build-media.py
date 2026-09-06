#!/usr/bin/env python3
"""Create private Windows 11 Pro installation media for a NEW 240 GiB VM.

The result contains a temporary image-builder password. Keep the work directory
private, publish the ISO only to forge-ci, and delete it after image sealing.
Never attach this unattended installer to an existing data or job volume.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from xml.sax.saxutils import escape


ISO_SHA256 = "768984706b909479417b2368438909440f2967ff05c6a9195ed2667254e465e3"
VIRTIO_SHA256 = "303f7ae40dad495d6ae474fdc571df58958a4dbc5c37a522d80f9a203867949d"
RUNNER_SHA256 = "cf2ae0bf1245b4d1fbff3a987c2544afa4e20807f2d70d47e59db4da84809fb4"


def verify(path, expected):
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != expected:
            raise RuntimeError(f"Checksum mismatch: {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("windows-iso", "virtio-iso", "tools", "runner", "operator-key", "work-directory"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    work = args.work_directory.resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = Path(__file__).resolve().parent
    verify(args.windows_iso, ISO_SHA256)
    verify(args.virtio_iso, VIRTIO_SHA256)
    verify(args.runner, RUNNER_SHA256)
    inputs = json.loads((source / "inputs.json").read_text())
    for item in inputs:
        verify(args.tools / item["name"], item["digest"].removeprefix("sha256:"))
    key = args.operator_key.read_text().strip()
    if not key.startswith("ssh-ed25519 ") or "\n" in key:
        raise ValueError("Expected one operator Ed25519 public key")
    media, drivers = work / "media", work / "drivers"
    for iso, destination in ((args.windows_iso, media), (args.virtio_iso, drivers)):
        subprocess.run(["7zz", "x", "-y", "-o" + str(destination), str(iso.resolve())],
                       check=True, stdout=subprocess.DEVNULL)
    for name in ("viostor", "vioscsi", "NetKVM", "vioserial", "Balloon", "viogpudo", "viorng", "fwcfg"):
        shutil.copytree(drivers / name / "w11/amd64", media / "$WinPEDriver$" / name)
    target = media / "sources/$OEM$/$1/Forge"
    target.mkdir(parents=True)
    (target / "tools").mkdir()
    for item in inputs:
        shutil.copy2(args.tools / item["name"], target / "tools" / item["name"])
    for name in ("Provision.ps1", "Update.ps1", "Seal.ps1", "Start-Job.ps1", "Run-Job.ps1",
                 "cloudbase-init.conf", "cloudbase-init-unattend.conf", "inputs.json"):
        shutil.copy2(source / name, target / name)
    shutil.copy2(args.runner, target / "forgejo-runner.exe")
    (target / "operator.pub").write_text(key + "\n")
    password = "Fj1!" + secrets.token_urlsafe(32)
    (work / "builder-credential.json").write_text(json.dumps({"username": "forge-builder", "password": password}) + "\n")
    xml = r'''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
 <settings pass="windowsPE">
  <component name="Microsoft-Windows-International-Core-WinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
   <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
   <InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale>
  </component>
  <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
   <DiskConfiguration><Disk wcm:action="add"><DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk>
    <CreatePartitions>
     <CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
     <CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
     <CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Size>244400</Size></CreatePartition>
     <CreatePartition wcm:action="add"><Order>4</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
    </CreatePartitions>
    <ModifyPartitions>
     <ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition>
     <ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition>
     <ModifyPartition wcm:action="add"><Order>3</Order><PartitionID>4</PartitionID><Format>NTFS</Format><Label>Recovery</Label><TypeID>de94bba4-06d1-4d40-a16a-bfd50179d6ac</TypeID></ModifyPartition>
    </ModifyPartitions>
   </Disk><WillShowUI>OnError</WillShowUI></DiskConfiguration>
   <ImageInstall><OSImage>
    <InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/NAME</Key><Value>Windows 11 Pro</Value></MetaData></InstallFrom>
    <InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo><WillShowUI>OnError</WillShowUI>
   </OSImage></ImageInstall>
   <UserData><AcceptEula>true</AcceptEula><FullName>Forge image builder</FullName><Organization>Homelab</Organization>
    <ProductKey><Key>VK7JG-NPHTM-C97JM-9MPGT-3V66T</Key><WillShowUI>OnError</WillShowUI></ProductKey>
   </UserData>
  </component>
 </settings>
 <settings pass="specialize">
  <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
   <ComputerName>forge-win-build</ComputerName><TimeZone>UTC</TimeZone>
  </component>
 </settings>
 <settings pass="oobeSystem">
  <component name="Microsoft-Windows-International-Core" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
   <InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale>
  </component>
  <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
   <OOBE><HideEULAPage>true</HideEULAPage><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><ProtectYourPC>1</ProtectYourPC></OOBE>
   <UserAccounts><LocalAccounts><LocalAccount wcm:action="add">
    <Name>forge-builder</Name><DisplayName>Temporary image builder</DisplayName><Group>Administrators</Group>
    <Password><Value>@PASSWORD@</Value><PlainText>true</PlainText></Password>
   </LocalAccount></LocalAccounts></UserAccounts>
   <AutoLogon><Enabled>true</Enabled><LogonCount>1</LogonCount><Username>forge-builder</Username>
    <Password><Value>@PASSWORD@</Value><PlainText>true</PlainText></Password>
   </AutoLogon>
   <FirstLogonCommands><SynchronousCommand wcm:action="add"><Order>1</Order>
    <CommandLine>powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\Forge\Provision.ps1</CommandLine>
    <Description>Qualify and provision the isolated image builder</Description>
   </SynchronousCommand></FirstLogonCommands>
  </component>
 </settings>
</unattend>
'''
    (media / "autounattend.xml").write_text(xml.replace("@PASSWORD@", escape(password)))
    # UDF is required for install.wim (>4 GiB). Preserve Microsoft's signed
    # EFI boot image; no modified bootloader or TPM/Secure Boot bypasses.
    output = work / "forge-windows-11-25h2-install.iso"
    subprocess.run(["mkisofs", "-quiet", "-iso-level", "3", "-udf", "-J", "-joliet-long",
                    "-V", "FORGE_WIN11", "-eltorito-platform", "efi", "-b", "efi/microsoft/boot/efisys.bin",
                    "-no-emul-boot", "-o", str(output), str(media)], check=True)
    with output.open("rb") as result:
        digest = hashlib.file_digest(result, "sha256").hexdigest()
    (work / "media-provenance.json").write_text(json.dumps({"sha256": digest,
        "source_iso_sha256": ISO_SHA256, "virtio_iso_sha256": VIRTIO_SHA256,
        "runner_sha256": RUNNER_SHA256, "private_builder_credential": True,
        "required_new_disk_gib": 240}, indent=2) + "\n")
    print(f"Private installer prepared: {output}; sha256={digest}")


if __name__ == "__main__":
    main()
