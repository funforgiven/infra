#!/usr/bin/env python3
"""Validate homelab manifests offline against pinned upstream schemas.

Renders every Kustomize entrypoint and every HelmRelease, validates the output
against the Kubernetes, KubeVirt and CRD schemas, and enforces repository
policies. Nix fetches the pinned charts and API documents (pins.json) and
passes their store paths with --inputs. No cluster, network or decryption:
Helm values from SOPS Secrets are left out of rendering.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import jsonschema
import yaml

yaml.SafeLoader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))

API_VERSIONS = ("monitoring.coreos.com/v1", "monitoring.coreos.com/v1/ServiceMonitor", "monitoring.coreos.com/v1/PodMonitor")
# Flux stages labelled with this stay suspended in the recovery overlay.
RECOVERY_HOLD = ("homelab.fahrican.com/recovery", "hold")
REMOTE_SCHEMA_REF = re.compile(r'"\$ref"\s*:\s*"https?://')


def key(document):
    return (document["kind"], document["metadata"].get("namespace", ""), document["metadata"]["name"])


def merge(left, right):
    for name, value in right.items():
        if isinstance(value, dict) and isinstance(left.get(name), dict):
            merge(left[name], value)
        else:
            left[name] = value


def run(command, what, **options):
    result = subprocess.run(command, capture_output=True, **options)
    if result.returncode:
        raise ValueError(what + " failed:\n" + result.stderr.decode(errors="replace").strip())
    return [document for document in yaml.safe_load_all(result.stdout) if document]


def kustomize(path):
    return run(["kustomize", "build", "--load-restrictor", "LoadRestrictionsNone", str(path)], "kustomize build " + str(path))


def strict(schema):
    """Tighten Kubernetes OpenAPI to what the API server accepts."""
    if not isinstance(schema, dict):
        return
    if schema.get("x-kubernetes-int-or-string") or schema.get("format") == "int-or-string":
        schema.pop("type", None)
        schema.pop("format", None)
        schema["anyOf"] = [{"type": "integer"}, {"type": "string"}]
    if schema.get("nullable") and "type" in schema:
        value = schema["type"]
        schema["type"] = value + ["null"] if isinstance(value, list) else [value, "null"]
    if schema.get("type") == "object" and "properties" in schema and not schema.get("x-kubernetes-preserve-unknown-fields"):
        schema.setdefault("additionalProperties", False)
    for name, value in list(schema.items()):
        if name in ["properties", "definitions", "patternProperties"]:
            for item in value.values():
                strict(item)
        elif name in ["items", "additionalProperties", "not"]:
            strict(value)
        elif name in ["allOf", "anyOf", "oneOf"]:
            for item in value:
                strict(item)


def omit_null_fields(value):
    """Match API decoding of omitted optional fields; required nulls still fail."""
    if isinstance(value, dict):
        return {name: omit_null_fields(item) for name, item in value.items() if item is not None}
    if isinstance(value, list):
        return [omit_null_fields(item) for item in value]
    return value


def validators(inputs, documents):
    """Kubernetes and KubeVirt API schemas plus every rendered CRD's schema."""
    swagger = json.loads(Path(inputs["kubernetes"]).read_text())
    schemas = {}
    for name, definition in swagger["definitions"].items():
        for gvk in definition.get("x-kubernetes-group-version-kind", []):
            version = (gvk["group"] + "/" if gvk["group"] else "") + gvk["version"]
            schemas[version + ":" + gvk["kind"]] = {"$ref": "#/definitions/" + name}
    # KubeVirt's operator creates its CRDs at runtime; use its versioned API.
    swagger["definitions"].update(json.loads(Path(inputs["kubevirt"]).read_text())["definitions"])
    for kind in ["KubeVirt", "VirtualMachine", "VirtualMachineInstance", "VirtualMachineInstanceMigration"]:
        schemas["kubevirt.io/v1:" + kind] = {"$ref": "#/definitions/v1." + kind}
    for document in documents:
        if document["kind"] == "CustomResourceDefinition":
            for version in document["spec"]["versions"]:
                schema = version.get("schema", {}).get("openAPIV3Schema")
                if schema:
                    schemas[document["spec"]["group"] + "/" + version["name"] + ":" + document["spec"]["names"]["kind"]] = copy.deepcopy(schema)
    for definition in swagger["definitions"].values():
        strict(definition)
    for schema in schemas.values():
        strict(schema)
    return {name: jsonschema.Draft7Validator({"allOf": [schema], "definitions": swagger["definitions"]}) for name, schema in schemas.items()}


def verify_vendors(root):
    for entry in json.loads((root / "deployments/homelab/validation/vendors.json").read_text())["files"]:
        if hashlib.sha256((root / entry["file"]).read_bytes()).hexdigest() != entry["localSHA256"]:
            raise ValueError("vendored manifest checksum mismatch: " + entry["file"])


def chart_source(release, objects):
    spec, namespace = release["spec"], release["metadata"]["namespace"]
    chart = None if "chartRef" in spec else spec["chart"]["spec"]
    reference = spec["chartRef"] if chart is None else chart["sourceRef"]
    return objects[(reference["kind"], reference.get("namespace", namespace), reference["name"])], chart


def require_pinned(release, source, chart, pin):
    """A HelmRelease's chart reference must be immutable and equal its pin."""
    name = release["metadata"]["namespace"] + "/" + release["metadata"]["name"]
    if pin is None:
        raise ValueError(name + ": HelmRelease has no entry in pins.json")
    spec = source["spec"]
    if source["kind"] == "OCIRepository":
        url, ref = spec["url"], spec.get("ref", {}).get("digest")
    elif source["kind"] == "GitRepository":
        ref = spec.get("ref", {}).get("commit")
        url = "https://codeload.github.com/" + spec["url"].removeprefix("https://github.com/").removesuffix(".git") + "/tar.gz/" + str(ref)
    else:  # HelmRepository: versions are immutable in the index; the pin hashes the archive.
        ref = chart["version"]
        url = pin["url"] if pin["url"].endswith("/" + chart["chart"] + "-" + ref + ".tgz") else chart["chart"] + "-" + ref + ".tgz"
    if ref is None:
        raise ValueError(name + ": chart source must pin a digest or commit")
    if (pin["url"], pin["ref"]) != (url, ref):
        raise ValueError(name + ": chart " + url + " " + ref + " differs from pins.json")


def unpack(archive, target):
    target.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter="data")
    return next(path for path in target.iterdir() if path.is_dir())


def release_values(release, objects):
    """Merge valuesFrom and inline values like Flux; returns (values, skipped Secrets)."""
    namespace = release["metadata"]["namespace"]
    config, skipped = {}, []
    for reference in release["spec"].get("valuesFrom", []):
        if reference.get("targetPath"):
            raise ValueError(release["metadata"]["name"] + ": valuesFrom targetPath is not supported")
        if reference["kind"] == "Secret":
            skipped.append(reference["name"])
            continue
        document = objects.get((reference["kind"], namespace, reference["name"]))
        if document is None:
            if reference.get("optional"):
                continue
            raise ValueError(release["metadata"]["name"] + ": missing valuesFrom " + reference["name"])
        merge(config, yaml.safe_load(document["data"][reference.get("valuesKey", "values.yaml")]) or {})
    merge(config, release["spec"].get("values", {}))
    return config, skipped


def helm_template(release, chart, config, kube_version):
    command = ["helm", "template", release["spec"].get("releaseName", release["metadata"]["name"]), str(chart),
               "--namespace", release["metadata"]["namespace"], "--kube-version", kube_version,
               "--include-crds", "--values", "-"]
    for version in API_VERSIONS:
        command += ["--api-versions", version]
    # Values schemas with remote $refs cannot be resolved offline.
    if any(REMOTE_SCHEMA_REF.search(path.read_text()) for path in chart.glob("values.schema.json")):
        print("Helm " + release["metadata"]["name"] + ": values schema has remote references; skipped")
        command.append("--skip-schema-validation")
    return run(command, "helm template " + release["metadata"]["name"], input=yaml.safe_dump(config).encode())


def render_releases(objects, pins, inputs, workdir):
    """Yield (release name, documents, chart directory) for every HelmRelease."""
    releases = sorted(key for key in objects if key[0] == "HelmRelease")
    stale = set(pins) - {namespace + "/" + name for _, namespace, name in releases}
    if stale:
        raise ValueError("pins.json lists charts without a HelmRelease: " + ", ".join(sorted(stale)))
    for _, namespace, name in releases:
        release, pinned = objects[("HelmRelease", namespace, name)], namespace + "/" + name
        source, chart = chart_source(release, objects)
        require_pinned(release, source, chart, pins.get(pinned))
        directory = unpack(inputs["charts"][pinned]["archive"], workdir / namespace / name)
        if source["kind"] == "GitRepository":
            directory = directory / chart["chart"]
        for index, dependency in enumerate(inputs["charts"][pinned]["dependencies"]):
            (directory / "charts").mkdir(exist_ok=True)
            shutil.copyfile(dependency, directory / "charts" / ("pinned-" + str(index) + ".tgz"))
        config, skipped = release_values(release, objects)
        if skipped:
            print("Helm " + name + ": rendered without SOPS values " + ", ".join(skipped))
        yield name, helm_template(release, directory, config, inputs["kubeVersion"]), directory


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


def require_inventory_copies(inventory, objects):
    """Manifests that cannot read hosts/inventory.json must repeat it exactly."""
    cluster, hosts = inventory["cluster"], inventory["hosts"]
    values = yaml.safe_load(objects[("ConfigMap", "kube-system", "cilium-values")]["data"]["values.yaml"])
    if values["k8sServiceHost"] != cluster["apiVip"]:
        raise ValueError("Cilium API host differs from the inventory VIP")
    zone = objects[("ConfigMap", "network-services", "internal-coredns")]["data"]["cloud.fahrican.com.zone"]
    records = {fields[0]: fields[3] for fields in (line.split() for line in zone.splitlines()) if fields[1:3] == ["IN", "A"]}
    expected = {name + ".mgmt": host["management"] for name, host in hosts.items()}
    expected[cluster["apiName"].removesuffix(".cloud.fahrican.com")] = cluster["apiVip"]
    if any(records.get(name) != address for name, address in expected.items()):
        raise ValueError("Internal DNS records differ from the inventory")
    nodes = {d["metadata"]["name"]: d["metadata"].get("annotations", {}).get("network.rook.io/mon-ip") for d in objects.values() if d["kind"] == "Node"}
    if nodes != {name: host["ceph"] for name, host in hosts.items()}:
        raise ValueError("Ceph monitor addresses differ from the inventory")


def require_isolated_restores(objects):
    """Every *-restore namespace must carry a policy denying ingress and egress."""
    for _, _, namespace in [k for k in objects if k[0] == "Namespace" and k[2].endswith("-restore")]:
        policies = [d["spec"] for (kind, ns, _), d in objects.items() if ns == namespace and kind in ("CiliumNetworkPolicy", "NetworkPolicy")]
        if not any(p.get("ingressDeny") == [{}] and p.get("egressDeny") == [{}] or
                   p.get("podSelector") == {} and sorted(p.get("policyTypes", [])) == ["Egress", "Ingress"]
                   and not p.get("ingress") and not p.get("egress") for p in policies):
            raise ValueError(namespace + ": restore namespace lacks a deny-all network policy")


def require_restore_drill_coverage(objects):
    """Both Velero schedules back up the same namespaces, each with a declared *-restore namespace."""
    lists = {name: sorted(d["spec"]["template"].get("includedNamespaces", []))
             for (kind, _, name), d in objects.items() if kind == "Schedule" and name in ("daily", "weekly")}
    if len(lists) != 2 or lists["daily"] != lists["weekly"]:
        raise ValueError("velero daily and weekly schedules must list the same namespaces")
    for namespace in lists["daily"]:
        if ("Namespace", "", namespace + "-restore") not in objects:
            raise ValueError(namespace + ": backed-up namespace has no " + namespace + "-restore namespace for the drill")


def require_monitoring_crds(objects, chart):
    """components/homelab/monitoring-crds must match the pinned kube-prometheus-stack chart."""
    shipped = {d["metadata"]["name"]: d["spec"] for path in sorted((chart / "charts/crds/crds").glob("*.yaml"))
               for d in yaml.safe_load_all(path.read_text()) if d}
    vendored = {name: d["spec"] for (kind, _, name), d in objects.items()
                if kind == "CustomResourceDefinition" and d["spec"]["group"] == "monitoring.coreos.com"}
    if not shipped or shipped != vendored:
        raise ValueError("components/homelab/monitoring-crds differs from the pinned kube-prometheus-stack CRDs; re-vendor them")


def require_shared_workload_health(waves):
    """HelmRelease waits must judge workloads exactly as the stage health checks do."""
    for wave in waves:
        stage = {(e["apiVersion"], e["kind"]): e for e in wave["spec"].get("healthCheckExprs", [])}
        patches = [p for p in wave["spec"].get("patches", []) if p.get("target", {}).get("kind") == "HelmRelease"]
        if len(patches) != 1:
            raise ValueError(wave["metadata"]["name"] + ": stage must patch HelmRelease health checks once")
        for expression in yaml.safe_load(patches[0]["patch"])[0]["value"]:
            if stage.get((expression["apiVersion"], expression["kind"])) != expression:
                raise ValueError(wave["metadata"]["name"] + ": HelmRelease health for " + expression["kind"] + " differs from the stage check")


def require_recovery_hold(waves, recovery):
    """Every stage labelled for recovery hold must be suspended by the overlay."""
    label, value = RECOVERY_HOLD
    held = {d["metadata"]["name"] for d in waves if d["metadata"].get("labels", {}).get(label) == value}
    if "ceph" not in held:
        raise ValueError("Ceph must stay held in the recovery overlay")
    paused = {d["metadata"]["name"] for d in recovery if d["kind"] == "Kustomization" and d["spec"].get("suspend")}
    if not held <= paused:
        raise ValueError("Recovery overlay releases Ceph or stateful applications prematurely")
    if paused - held:
        raise ValueError("Recovery overlay suspends stages without the hold label")


def require_flux_graph(root, waves):
    graph = {d["metadata"]["name"]: [dependency["name"] for dependency in d["spec"].get("dependsOn", [])] for d in waves}

    def visit(name, ancestors=()):
        if name in ancestors:
            raise ValueError("Flux dependency cycle: " + name)
        if name not in graph:
            raise ValueError("Missing Flux dependency: " + name)
        for dependency in graph[name]:
            visit(dependency, ancestors + (name,))
    for name in graph:
        visit(name)
    for wave in waves:
        path = (root / wave["spec"]["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not (path / "kustomization.yaml").is_file():
            raise ValueError(wave["metadata"]["name"] + ": invalid Flux path " + wave["spec"]["path"])


def unknown_storage_classes(objects):
    known = {d["metadata"]["name"] for d in objects.values() if d["kind"] == "StorageClass"}
    found = set()

    def inspect(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if name in ["storageClassName", "storageClass"] and isinstance(item, str) and item and item not in known:
                    found.add(item)
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
    for document in objects.values():
        if document["kind"] not in ["CustomResourceDefinition", "HelmRelease"]:
            inspect(document)
    return ["unknown storage class: " + name for name in sorted(found)]


def schema_failures(schemas, document, source):
    document = omit_null_fields(copy.deepcopy(document))
    document.pop("sops", None)
    if document.get("kind") == "Secret":
        # SOPS ciphertext is not Kubernetes base64.
        if "data" in document:
            document["data"] = {name: "AA==" for name in document["data"]}
        if "stringData" in document:
            document["stringData"] = {name: "" for name in document["stringData"]}
    gvk = document["apiVersion"] + ":" + document["kind"]
    identity = gvk + " " + document["metadata"].get("namespace", "") + "/" + document["metadata"]["name"]
    if gvk not in schemas:
        return [source + ": missing schema for " + identity]
    failures = [source + ": " + identity + " at /" + "/".join(map(str, error.absolute_path)) + ": " + error.message[:300]
                for error in schemas[gvk].iter_errors(document)]
    if document["kind"] == "ConfigMap":
        for name, value in (document.get("data") or {}).items():
            if not name.endswith((".yaml", ".json")):
                continue
            try:
                embedded = list(yaml.safe_load_all(value))
            except yaml.YAMLError:
                continue
            for item in embedded:
                if isinstance(item, dict) and all(field in item for field in ["apiVersion", "kind", "metadata"]):
                    failures += schema_failures(schemas, item, source + " embedded " + name)
    return failures


def validate(root, inputs):
    pins = json.loads((root / "deployments/homelab/validation/pins.json").read_text())
    if "/v" + inputs["kubeVersion"] + "/" not in pins["kubernetes"]["url"]:
        raise ValueError("pins.json Kubernetes API does not match the hosts' K3s " + inputs["kubeVersion"])
    pins = pins["charts"]
    verify_vendors(root)
    rendered, objects = [], {}
    for path in sorted((root / "deployments/homelab").rglob("kustomization.yaml")):
        if "routeros" not in path.parts:
            source = str(path.parent.relative_to(root))
            for document in kustomize(path.parent):
                rendered.append((source, document))
                objects[key(document)] = document
    with tempfile.TemporaryDirectory() as workdir:
        for name, documents, chart in render_releases(objects, pins, inputs, Path(workdir)):
            rendered += [("Helm " + name, document) for document in documents]
            if name == "kube-prometheus-stack":
                require_monitoring_crds(objects, chart)
    schemas = validators(inputs, [document for _, document in rendered])
    failures = [failure for source, document in rendered for failure in schema_failures(schemas, document, source)]
    waves = [d for d in kustomize(root / "deployments/homelab/cluster") if d["kind"] == "Kustomization" and d["metadata"]["name"] != "flux-system"]
    require_flux_graph(root, waves)
    require_recovery_hold(waves, kustomize(root / "deployments/homelab/recovery"))
    require_shared_workload_health(waves)
    require_bounded_postgres_wal(objects)
    require_isolated_restores(objects)
    require_restore_drill_coverage(objects)
    require_inventory_copies(json.loads((root / "deployments/homelab/hosts/inventory.json").read_text()), objects)
    failures += unknown_storage_classes(objects)
    for failure in sorted(set(failures)):
        print(failure)
    print(json.dumps({"resources": len(rendered), "helmReleases": len(pins), "schemas": len(schemas), "failures": len(failures)}))
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--inputs", type=Path, required=True, help="JSON written by Nix: kubeVersion and pinned store paths")
    args = parser.parse_args()
    try:
        return validate(args.repository_root, json.loads(args.inputs.read_text()))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
