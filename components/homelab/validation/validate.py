#!/usr/bin/env python3
"""Validate all prepared Kustomize resources against pinned upstream schemas.

No cluster or provider calls. Optional Helm rendering uses an existing local
chart cache. Secret values and schema failure instances are never printed.
"""
import argparse
import copy
import gzip
import json
import re
from pathlib import Path

import jsonschema
import yaml

from manifests import RECOVERY_HOLD, decrypted_objects, entrypoints as rendered_entrypoints, helm_template, key, release_values, render, verify_vendors

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

def require_bounded_postgres_wal(objects):
    """Keep an offline replica's WAL budget within half its storage volume."""
    units = {"MB": 2**20, "GB": 2**30, "TB": 2**40, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}
    for document in objects.values():
        if document.get("apiVersion") != "postgresql.cnpg.io/v1" or document.get("kind") != "Cluster":
            continue
        spec = document["spec"]
        if spec.get("instances", 1) < 2:
            continue
        name = document["metadata"]["name"]
        limit = str(spec.get("postgresql", {}).get("parameters", {}).get("max_slot_wal_keep_size", ""))
        wal = re.fullmatch(r"([1-9][0-9]*)\s*(MB|GB|TB)", limit)
        storage = spec.get("walStorage") or spec.get("storage", {})
        disk = re.fullmatch(r"([1-9][0-9]*)(Mi|Gi|Ti)", storage.get("size", ""))
        if not wal or not disk:
            raise ValueError(name + ": replicated PostgreSQL requires an explicit finite WAL budget and volume size")
        if int(wal[1]) * units[wal[2]] > int(disk[1]) * units[disk[2]] // 2:
            raise ValueError(name + ": replica WAL budget exceeds half its storage volume")

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

def require_inventory_copies(inventory,objects):
    """Manifests that cannot read hosts/inventory.json must repeat it exactly."""
    cluster,hosts=inventory["cluster"],inventory["hosts"]
    values=yaml.safe_load(objects[("ConfigMap","kube-system","cilium-values")]["data"]["values.yaml"])
    if values["k8sServiceHost"]!=cluster["apiVip"]:raise ValueError("Cilium API host differs from the inventory VIP")
    zone=objects[("ConfigMap","network-services","internal-coredns")]["data"]["cloud.fahrican.com.zone"]
    records={fields[0]:fields[3] for fields in (line.split() for line in zone.splitlines()) if fields[1:3]==["IN","A"]}
    expected={name+".mgmt":host["management"] for name,host in hosts.items()}
    expected[cluster["apiName"].removesuffix(".cloud.fahrican.com")]=cluster["apiVip"]
    if any(records.get(name)!=address for name,address in expected.items()):raise ValueError("Internal DNS records differ from the inventory")
    nodes={d["metadata"]["name"]:d["metadata"].get("annotations",{}).get("network.rook.io/mon-ip") for d in objects.values() if d["kind"]=="Node"}
    if nodes!={name:host["ceph"] for name,host in hosts.items()}:raise ValueError("Ceph monitor addresses differ from the inventory")

def require_shared_workload_health(waves):
    """HelmRelease waits must judge workloads exactly as the stage health checks do."""
    for wave in waves:
        stage={(e["apiVersion"],e["kind"]):e for e in wave["spec"].get("healthCheckExprs",[])}
        patches=[p for p in wave["spec"].get("patches",[]) if p.get("target",{}).get("kind")=="HelmRelease"]
        if len(patches)!=1:raise ValueError(wave["metadata"]["name"]+": stage must patch HelmRelease health checks once")
        for expression in yaml.safe_load(patches[0]["patch"])[0]["value"]:
            if stage.get((expression["apiVersion"],expression["kind"]))!=expression:
                raise ValueError(wave["metadata"]["name"]+": HelmRelease health for "+expression["kind"]+" differs from the stage check")

def require_recovery_hold(waves,recovery):
    """Every stage labelled for recovery hold must be suspended by the overlay."""
    label,value=RECOVERY_HOLD
    held={d["metadata"]["name"] for d in waves if d["metadata"].get("labels",{}).get(label)==value}
    if "ceph" not in held:raise ValueError("Ceph must stay held in the recovery overlay")
    paused={d["metadata"]["name"] for d in recovery if d["kind"]=="Kustomization" and d["spec"].get("suspend")}
    if not held<=paused:raise ValueError("Recovery overlay releases Ceph or stateful applications prematurely")
    if paused-held:raise ValueError("Recovery overlay suspends stages without the hold label")

def validate(root,kustomize,helm_cache=None,decrypt=False,helm="helm"):
    bundle=json.loads(gzip.decompress((root/"deployments/homelab/validation/schemas.json.gz").read_bytes()))
    strict(bundle["definitions"])
    for definition in bundle["definitions"].values():strict(definition)
    for schema in bundle["schemas"].values():strict(schema)
    validators={key:jsonschema.Draft7Validator({"allOf":[schema],"definitions":bundle["definitions"]}) for key,schema in bundle["schemas"].items()}
    verify_vendors(root)
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
    for source,objects in rendered_entrypoints(root,kustomize):
        entrypoints.append(source)
        for document in objects:
            check(document,source)
            all_objects[key(document)]=document
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
    require_recovery_hold(waves,render(kustomize,root/"deployments/homelab/recovery"))
    require_shared_workload_health(waves)
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
    require_bounded_postgres_wal(all_objects)
    require_inventory_copies(json.loads((root/"deployments/homelab/hosts/inventory.json").read_text()),all_objects)
    helm_count=0
    if helm_cache:
        charts=json.loads((helm_cache/"charts.json").read_text())
        secrets=decrypted_objects(root) if decrypt else None
        for release in [d for d in all_objects.values() if d["kind"]=="HelmRelease"]:
            name=release["metadata"]["name"]
            chart=charts[release["metadata"]["namespace"]+"/"+name]
            for document in helm_template(helm,release,chart["path"],release_values(release,all_objects,secrets)):
                check(document,"Helm "+name);helm_count+=1
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
