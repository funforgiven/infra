"""Small, offline helpers for encrypted migration inputs."""
import base64
import os
from pathlib import Path
import subprocess
import yaml

def decrypt(path):
    r=subprocess.run(["sops","decrypt",str(path)],capture_output=True,check=True)
    return list(yaml.safe_load_all(r.stdout))

def values(document):
    return document.get("stringData") or {k:base64.b64decode(v).decode() for k,v in document.get("data",{}).items()}

def save(root,relative,documents):
    path=root/relative
    if path.exists() and decrypt(path)==documents: return False
    result=subprocess.run(["sops","encrypt","--filename-override",str(relative),"--input-type","yaml","--output-type","yaml","/dev/stdin"],input=yaml.safe_dump_all(documents,sort_keys=False).encode(),capture_output=True,check=True,cwd=root)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".new")
    with open(temporary,"wb") as stream: stream.write(result.stdout)
    temporary.replace(path)
    return True

def secret(name,namespace,data):
    return {"apiVersion":"v1","kind":"Secret","metadata":{"name":name,"namespace":namespace},"type":"Opaque","stringData":data}
