#!/usr/bin/env python3
"""Export preserved independent provider states locally; never call a provider API."""
import argparse
import base64
import gzip
import json
import os
from pathlib import Path
from encrypted_inputs import decrypt

STATE_NAMES={"identity":"tfstate-default-zitadel","dns":"tfstate-default-service-dns","mail-aws":"tfstate-default-mail-aws","netbird":"tfstate-default-netbird-policy"}

def read_state(snapshot,provider):
    name=STATE_NAMES[provider]
    matches=[o for o in snapshot["objects"] if o["metadata"]["name"]==name]
    if len(matches)!=1: raise ValueError("ambiguous archived state")
    payload=base64.b64decode(matches[0]["data"]["tfstate"],validate=True)
    if payload.startswith(b"\x1f\x8b"): payload=gzip.decompress(payload)
    state=json.loads(payload)
    if state.get("version")!=4 or not state.get("lineage"): raise ValueError("unsupported or unidentifiable state")
    return state

def current_snapshot():
    current=Path("secrets/current-provider-state.sops.yaml")
    return current if current.exists() else Path("secrets/migration-state.sops.yaml")

def outputs(provider):
    return read_state(decrypt(current_snapshot())[0],provider).get("outputs",{})

def export(snapshot,provider,target):
    state=read_state(snapshot,provider)
    payload=json.dumps(state).encode()

    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"wb") as stream: stream.write(payload)
    return len(state.get("resources",[]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider",choices=STATE_NAMES)
    parser.add_argument("--snapshot",type=Path,default=current_snapshot())
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    count=export(decrypt(args.snapshot)[0],args.provider,args.output)
    print(f"Exported {args.provider} state with {count} resource groups to an owner-only file; no provider API calls.")

if __name__=="__main__":
    os.umask(0o077)
    try: main()
    except Exception: raise SystemExit("State export failed; check the encrypted snapshot, recipient access and a nonexistent output path. State diagnostics suppressed.") from None
