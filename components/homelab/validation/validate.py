#!/usr/bin/env python3
"""Validate all prepared Kustomize resources against pinned upstream schemas.

No cluster or provider calls. Optional Helm rendering uses an existing local
chart cache. Secret values and schema failure instances are never printed.
"""
import argparse
import copy
import gzip
import json
from pathlib import Path
import subprocess
import sys

import jsonschema
import yaml
yaml.SafeLoader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))

def strict(schema):
    if not isinstance(schema,dict):return
    if schema.get("x-kubernetes-int-or-string") or schema.get("format") == "int-or-string":
        schema.pop("type",None)
        schema.pop("format",None)
        schema["anyOf"]=[{"type":"integer"},{"type":"string"}]
    if schema.get("nullable") and "type" in schema:
        value=schema["type"]
        schema["type"]=value+["null"] if isinstance(value,list) else [value,"null"]
    if schema.get("type")=="object" and "properties" in schema and not schema.get("x-kubernetes-preserve-unknown-fields"):
        schema.setdefault("additionalProperties",False)
    for key,value in list(schema.items()):
        if key in ["properties","definitions","patternProperties"]:
            for item in value.values():strict(item)
        elif key in ["items","additionalProperties","not"]:strict(value)
        elif key in ["allOf","anyOf","oneOf"]:
            for item in value:strict(item)

def omit_null_fields(value):
    """Match API decoding of omitted optional fields; required nulls still fail."""
    if isinstance(value, dict):
        return {key: omit_null_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_null_fields(item) for item in value]
    return value

def merge(left,right):
    for key,value in right.items():
        if isinstance(value,dict) and isinstance(left.get(key),dict):merge(left[key],value)
        else:left[key]=value

def render(kustomize,path):
    result=subprocess.run([kustomize,"build","--load-restrictor","LoadRestrictionsNone",str(path)],capture_output=True)
    if result.returncode:raise ValueError("Kustomize build failed: "+str(path))
    return [d for d in yaml.safe_load_all(result.stdout) if d]

def require_snapshot_support(objects):
    if any(d["kind"] == "VolumeSnapshotClass" for d in objects.values()):
        required_snapshot_crds = {"volumesnapshots.snapshot.storage.k8s.io", "volumesnapshotcontents.snapshot.storage.k8s.io", "volumesnapshotclasses.snapshot.storage.k8s.io"}
        declared_crds = {d["metadata"]["name"] for d in objects.values() if d["kind"] == "CustomResourceDefinition"}
        if not required_snapshot_crds <= declared_crds:
            raise ValueError("Snapshot backup requires installed snapshot API CRDs")
        if ("Deployment", "kube-system", "snapshot-controller") not in objects:
            raise ValueError("Snapshot backup requires its independent controller")
        drivers = objects[("HelmRelease", "rook-ceph", "ceph-csi-drivers")]
        if drivers["spec"]["values"]["drivers"]["rbd"]["snapshotPolicy"] != "volumeSnapshot":
            raise ValueError("Forgejo snapshot backup requires enabled RBD CSI snapshots")

def validate(root,kustomize,helm_cache=None,decrypt=False,helm="helm"):
    bundle=json.loads(gzip.decompress((root/"deployments/homelab/validation/schemas.json.gz").read_bytes()))
    strict(bundle["definitions"])
    for definition in bundle["definitions"].values():strict(definition)
    for schema in bundle["schemas"].values():strict(schema)
    validators={key:jsonschema.Draft7Validator({"allOf":[schema],"definitions":bundle["definitions"]}) for key,schema in bundle["schemas"].items()}
    import hashlib
    vendors = json.loads((root/'deployments/homelab/validation/vendors.json').read_text())
    for entry in vendors['files']:
        if hashlib.sha256((root/entry['file']).read_bytes()).hexdigest() != entry['localSHA256']:
            raise ValueError('vendored manifest checksum mismatch: ' + entry['file'])
    failures=[]
    checked=0
    def check(document,source):
        nonlocal checked
        document=omit_null_fields(copy.deepcopy(document))
        document.pop("sops",None)
        if document.get("kind")=="Secret":
            # SOPS ciphertext is not Kubernetes base64. Decrypted Helm values
            # are validated in memory when --decrypt is requested.
            if "data" in document:document["data"]={key:"AA==" for key in document["data"]}
            if "stringData" in document:document["stringData"]={key:"REDACTED" for key in document["stringData"]}
        key=document["apiVersion"]+":"+document["kind"]
        identity=key+" "+document["metadata"].get("namespace","")+"/"+document["metadata"]["name"]
        if key not in validators:failures.append(source+": missing schema "+identity);return
        for error in validators[key].iter_errors(document):
            # Never include error.message: it can interpolate a secret value.
            failures.append(source+": "+identity+" field "+"/".join(map(str,error.absolute_path))+" violates "+error.validator)
        checked+=1
        if document["kind"]=="ConfigMap":
            for name,value in (document.get("data") or {}).items():
                if not name.endswith((".yaml",".json")):continue
                try: embedded=list(yaml.safe_load_all(value))
                except yaml.YAMLError:continue
                for item in embedded:
                    if isinstance(item,dict) and all(key in item for key in ["apiVersion","kind","metadata"]):check(item,source+" embedded "+name)
    all_objects={}
    entrypoints=[]
    for path in sorted((root/"deployments/homelab").rglob("kustomization.yaml")):
        if "routeros" in path.parts:continue
        source=str(path.parent.relative_to(root))
        objects=render(kustomize,path.parent)
        entrypoints.append(source)
        for document in objects:
            check(document,source)
            all_objects[(document["kind"],document["metadata"].get("namespace",""),document["metadata"]["name"])]=document
    waves=[document for document in render(kustomize,root/"deployments/homelab/cluster") if document["kind"]=="Kustomization" and document["metadata"]["name"]!="flux-system"]
    graph={d["metadata"]["name"]:[dep["name"] for dep in d["spec"].get("dependsOn",[])] for d in waves}
    def visit(name,ancestors=()):
        if name in ancestors:raise ValueError("Flux dependency cycle: "+name)
        if name not in graph:raise ValueError("Missing Flux dependency: "+name)
        for dependency in graph[name]:visit(dependency,ancestors+(name,))
    for name in graph:visit(name)
    for wave in waves:
        path=(root/wave["spec"]["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not (path/"kustomization.yaml").is_file():raise ValueError("Invalid Flux path")
    recovery=render(kustomize,root/"deployments/homelab/recovery")
    paused={d["metadata"]["name"] for d in recovery if d["kind"]=="Kustomization" and d["spec"].get("suspend")}
    required={"ceph","observability","identity-database","identity","unifi","home-automation","media","wallos","forge","matrix","factorio","valheim","netbird"}
    if not required<=paused:raise ValueError("Recovery overlay releases Ceph or stateful applications prematurely")
    storage={d["metadata"]["name"] for d in all_objects.values() if d["kind"]=="StorageClass"}
    def inspect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ["storageClassName","storageClass"] and isinstance(item,str) and item and item not in storage:failures.append("Unknown direct storage class: "+item)
                inspect(item)
        elif isinstance(value,list):
            for item in value:inspect(item)
    for d in all_objects.values():
        if d["kind"] not in ["CustomResourceDefinition","HelmRelease"]:inspect(d)
    require_snapshot_support(all_objects)
    helm_count=0
    if helm_cache:
        charts=json.loads((helm_cache/"charts.json").read_text())
        secrets={}
        if decrypt:
            sys.path.insert(0,str(root/"components/homelab/operations"))
            from encrypted_inputs import decrypt as open_encrypted,values
            for path in (root/"deployments/homelab/cluster").rglob("*.sops.yaml"):
                for d in open_encrypted(path):
                    if d.get("kind") in ["Secret","ConfigMap"]:secrets[(d["kind"],d["metadata"].get("namespace",""),d["metadata"]["name"])]=d
        releases=[d for d in all_objects.values() if d["kind"]=="HelmRelease"]
        for release in releases:
            namespace=release["metadata"]["namespace"]
            name=release["metadata"]["name"]
            chart=charts[namespace+"/"+name]
            config={}
            for reference in release["spec"].get("valuesFrom",[]):
                key=(reference["kind"],namespace,reference["name"])
                d=secrets.get(key,all_objects.get(key))
                if d is None and reference.get("optional"):continue
                if d is None:raise ValueError("Missing valuesFrom resource for "+name)
                if d.get("sops"):raise ValueError("Use --decrypt to validate encrypted Helm values")
                if d["kind"]=="Secret":
                    if not decrypt:raise ValueError("Use --decrypt to validate Secret Helm values")
                    payload=values(d)[reference.get("valuesKey","values.yaml")]
                else:payload=d["data"][reference.get("valuesKey","values.yaml")]
                if reference.get("targetPath"):raise ValueError("Explicit targetPath support required")
                merge(config,yaml.safe_load(payload) or {})
            merge(config,release["spec"].get("values",{}))
            cmd=[helm,"template",release["spec"].get("releaseName",name),chart["path"],"--namespace",namespace,"--kube-version","1.36.4","--include-crds","--values","/dev/stdin","--api-versions","monitoring.coreos.com/v1","--api-versions","monitoring.coreos.com/v1/ServiceMonitor","--api-versions","monitoring.coreos.com/v1/PodMonitor"]
            result=subprocess.run(cmd,input=yaml.safe_dump(config).encode(),capture_output=True)
            if result.returncode:raise ValueError("Helm render failed for "+name+"; diagnostics suppressed")
            for document in yaml.safe_load_all(result.stdout):
                if document:check(document,"Helm "+name);helm_count+=1
    for failure in sorted(set(failures)):print(failure)
    print(json.dumps({"entrypoints":len(entrypoints),"fluxStages":len(graph),"validatedResources":checked,"helmResources":helm_count,"failures":len(failures)}))
    return 1 if failures else 0

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root",type=Path,default=Path.cwd())
    parser.add_argument("--kustomize",default="kustomize")
    parser.add_argument("--helm",default="helm")
    parser.add_argument("--helm-cache",type=Path)
    parser.add_argument("--decrypt",action="store_true")
    args=parser.parse_args()
    return validate(args.repository_root,args.kustomize,args.helm_cache,args.decrypt,args.helm)
if __name__=="__main__":
    try:raise SystemExit(main())
    except Exception as error:raise SystemExit("Validation could not complete ("+type(error).__name__+"); value-bearing diagnostics suppressed.") from None
