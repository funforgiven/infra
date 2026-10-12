#!/usr/bin/env python3
"""Read the frozen source deployment into a new private recovery directory.

No cluster/provider writes, backup jobs, target edits or plaintext secret files.
Cloud SDK execution belongs to the old flake's access environment, not the target.
"""
import argparse
import base64
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urljoin, urlsplit

import yaml


class CaptureError(ValueError):
    """A diagnostic constructed only from local constants/status codes."""


STATE_INPUTS = {
    "tofu-system": ["zitadel-identity-outputs", "tfstate-default-zitadel",
                    "tfstate-default-services-identity", "tfstate-default-netbird-policy",
                    "netbird-policy-credentials", "tofu-zitadel-credentials"],
    "cert-manager": ["tfstate-default-service-dns", "cloudflare-dns01", "letsencrypt-cloudflare-account"],
    "network-services": ["management-tls"],
    "openstack": ["tfstate-default-mail-aws", "services-runtime-bootstrap", "services-backup-destination"],
    "observability": ["grafana-oidc", "grafana-admin-credentials"],
    "identity": ["zitadel-secrets", "zitadel-login-service-key", "zitadel-b2-backup"],
}
CONTROLLERS = ("deployments,statefulsets,daemonsets,cronjobs,jobs,services,"
               "kustomizations.kustomize.toolkit.fluxcd.io,helmreleases.helm.toolkit.fluxcd.io")
CLOUD_QUERIES = [
    ("servers", "compute", "/servers/detail", "id name status tenant_id user_id flavor image addresses key_name OS-EXT-SRV-ATTR:host OS-EXT-SRV-ATTR:hypervisor_hostname OS-EXT-AZ:availability_zone os-extended-volumes:volumes_attached"),
    ("volumes", "volumev3", "/volumes/detail", "id name status size volume_type bootable encrypted attachments snapshot_id source_volid os-vol-tenant-attr:tenant_id os-vol-host-attr:host"),
    ("snapshots", "volumev3", "/snapshots/detail", "id name status size volume_id created_at os-extended-snapshot-attributes:project_id"),
    ("shares", "sharev2", "/shares/detail", "id name status size share_proto share_type share_network_id project_id host snapshot_id is_public"),
    ("floatingips", "network", "/v2.0/floatingips", "id floating_ip_address fixed_ip_address port_id router_id project_id status"),
    ("images", "image", "/v2/images", "id name status size virtual_size disk_format container_format visibility owner"),
]


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, check=True, timeout=240, **kwargs).stdout


def fields(obj, names):
    return {key: obj[key] for key in names.split() if key in obj}


def clean_object(obj):
    result = fields(obj, "apiVersion kind type data binaryData immutable spec status")
    result["metadata"] = fields(obj["metadata"], "name namespace uid labels annotations")
    return result


def public_volume(obj):
    result = fields(obj, "apiVersion kind")
    result["metadata"] = fields(obj["metadata"], "name namespace")
    labels = obj["metadata"].get("labels", {})
    result["metadata"]["labels"] = {k: v for k, v in labels.items() if k.startswith(
        ("app.kubernetes.io/", "kustomize.toolkit.fluxcd.io/", "cnpg.io/", "velero.io/"))}
    spec = obj.get("spec", {})
    result["spec"] = fields(spec, "accessModes capacity resources storageClassName volumeMode volumeName persistentVolumeReclaimPolicy mountOptions")
    if "claimRef" in spec: result["spec"]["claimRef"] = fields(spec["claimRef"], "name namespace uid")
    if "csi" in spec:
        csi = fields(spec["csi"], "driver volumeHandle fsType readOnly")
        csi["volumeAttributes"] = fields(spec["csi"].get("volumeAttributes", {}),
            "clusterID pool imageName fsName subvolumeName subvolumePath shareID shareId staticVolume storage.kubernetes.io/csiProvisionerIdentity")
        result["spec"]["csi"] = csi
    if "cinder" in spec: result["spec"]["cinder"] = fields(spec["cinder"], "volumeID fsType readOnly")
    if "nfs" in spec: result["spec"]["nfs"] = fields(spec["nfs"], "server path readOnly")
    result["status"] = fields(obj.get("status", {}), "phase capacity accessModes")
    return result


def public_controller(obj):
    result = fields(obj, "apiVersion kind")
    result["metadata"] = fields(obj["metadata"], "name namespace uid")
    spec = obj.get("spec", {})
    result["spec"] = fields(spec, "replicas suspend")
    if obj["kind"] == "Service":
        result["spec"].update(fields(spec, "type clusterIP clusterIPs loadBalancerIP externalIPs"))
        result["spec"]["ports"] = [fields(p, "name port targetPort protocol nodePort") for p in spec.get("ports", [])]
        result["status"] = {"loadBalancer": obj.get("status", {}).get("loadBalancer", {})}
    return result


def private_directory(output, roots):
    output = output.resolve()
    if any(output.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("capture must be outside both repositories")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.mkdir(mode=0o700)  # A complete new directory; never merge or overwrite.
    return output


def write_file(output, name, payload):
    descriptor = os.open(output / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream: stream.write(payload)
    return {"file": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def encrypt(root, name, obj):
    return run(["sops", "encrypt", "--filename-override", "secrets/" + name,
                "--input-type", "yaml", "--output-type", "yaml", "/dev/stdin"],
               input=yaml.safe_dump(obj, sort_keys=False).encode(), cwd=root)


def endpoint_path(endpoint, path):
    endpoint = endpoint.rstrip("/")
    for version in ("/v2.0", "/v2"):
        if endpoint.endswith(version) and path.startswith(version + "/"):
            path = path[len(version):]
            break
    return endpoint + path


def get_json(session, url, params=None, headers=None):
    response = session.get(url, params=params, headers=headers, raise_exc=False, timeout=60)
    if response.status_code != 200: raise CaptureError("source API returned HTTP " + str(response.status_code))
    return response.json()


def paginated(session, endpoint, path, collection, params=None, headers=None):
    url = endpoint_path(endpoint, path)
    origin = urlsplit(endpoint)
    prefix = origin.path.rstrip("/") + "/"
    seen = set()
    objects = []
    while url:
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc) or not parsed.path.startswith(prefix):
            raise CaptureError("source pagination left its catalog endpoint")
        if url in seen: raise CaptureError("source pagination loop")
        seen.add(url)
        document = get_json(session, url, params, headers)
        params = None
        objects.extend(document[collection])
        links = [link["href"] for link in document.get(collection + "_links", []) if link.get("rel") == "next"]
        if document.get("next"): links.append(document["next"])
        if len(links) > 1: raise ValueError("ambiguous source pagination")
        url = urljoin(url, links[0]) if links else None
    ids = [obj["id"] for obj in objects]
    if len(ids) != len(set(ids)): raise ValueError("duplicate source IDs across pages")
    return objects


def collect_cloud():
    # Only reached inside the frozen source matrix-access Python environment.
    import openstack
    source = json.loads(run(["kubectl", "--request-timeout=30s", "-n", "openstack",
                             "get", "secret", "magnum-keystone-admin", "-o", "json"]))
    auth = {key: base64.b64decode(value, validate=True).decode() for key, value in source["data"].items() if key.startswith("OS_")}
    region = auth.get("OS_REGION_NAME", "RegionOne")
    connection = openstack.connection.Connection(auth={
        "auth_url": "https://identity.cloud.fahrican.com/v3", "username": auth["OS_USERNAME"],
        "password": auth["OS_PASSWORD"], "user_domain_name": auth.get("OS_USER_DOMAIN_NAME", "Default"),
        "project_name": auth.get("OS_PROJECT_NAME", "admin"),
        "project_domain_name": auth.get("OS_PROJECT_DOMAIN_NAME", "Default"),
    }, interface="public", region_name=region)
    session = connection.session
    endpoints = {}
    def endpoint(kind):
        if kind not in endpoints:
            endpoints[kind] = session.get_endpoint(service_type=kind, interface="public", region_name=region)
            if not endpoints[kind]: raise ValueError("source catalog endpoint absent")
        return endpoints[kind]
    records = {"errors": []}
    for name, kind, path, allowed in CLOUD_QUERIES:
        print("Reading source cloud " + name, file=os.sys.stderr, flush=True)
        original = paginated(session, endpoint(kind), path, name,
                             {"all_tenants": 1} if kind in ("compute", "volumev3", "sharev2") else None,
                             {"X-OpenStack-Manila-API-Version": "2.9"} if kind == "sharev2" else None)
        records[name] = [fields(obj, allowed) for obj in original]
        if name == "volumes":
            for raw, obj in zip(original, records[name]):
                obj["imageMetadata"] = fields(raw.get("volume_image_metadata", {}),
                    "image_id image_name disk_format container_format os_type os_distro os_version")
        if name == "shares":
            for share in records[name]:
                exports = get_json(session, endpoint(kind).rstrip("/") + "/shares/" + share["id"] + "/export_locations",
                                   headers={"X-OpenStack-Manila-API-Version": "2.9"})
                share["exports"] = [fields(obj, "id path is_admin_only") for obj in exports["export_locations"]]
    owners = {"ports": [], "loadbalancers": [], "errors": []}
    for floating in records["floatingips"]:
        if not floating.get("port_id"): continue  # An allocated but unassociated FIP is still inventoried.
        port = get_json(session, endpoint_path(endpoint("network"), "/v2.0/ports/" + floating["port_id"]))["port"]
        owners["ports"].append(dict(fields(port, "id name device_owner device_id fixed_ips network_id project_id status"),
                                    floatingAddress=floating["floating_ip_address"]))
    owners["loadbalancers"] = [fields(obj, "id name vip_address vip_port_id project_id provisioning_status operating_status")
        for obj in paginated(session, endpoint("load-balancer"), "/v2/lbaas/loadbalancers", "loadbalancers")]
    return {"cloud": records, "owners": owners}


def certificate_record(cluster, obj):
    record = dict(fields(obj["metadata"], "namespace name"), sourceCluster=cluster,
                  type=obj.get("type", "Opaque"), fields=sorted(obj.get("data", {})))
    if record["type"] == "kubernetes.io/tls":
        certificate = base64.b64decode(obj["data"]["tls.crt"], validate=True)
        record["certificateSHA256"] = hashlib.sha256(run(["openssl", "x509", "-outform", "DER"], input=certificate)).hexdigest()
        record["notAfter"] = run(["openssl", "x509", "-enddate", "-noout"], input=certificate).decode().strip().removeprefix("notAfter=")
    if record["name"].startswith("tfstate-"):
        raw = base64.b64decode(obj["data"]["tfstate"], validate=True)
        state = json.loads(gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw)
        if state.get("version") != 4 or not state.get("lineage"): raise ValueError("unidentifiable provider state")
        record.update(stateLineage=state["lineage"], stateSerial=state["serial"], stateResourceGroups=len(state.get("resources", [])))
    return record


def state_inputs(objects):
    indexed = {(obj["kind"], obj["metadata"]["namespace"], obj["metadata"]["name"]): obj for obj in objects}
    result = []
    for namespace, names in STATE_INPUTS.items():
        for name in names:
            kind = "ConfigMap" if name == "services-backup-destination" else "Secret"
            result.append(indexed[(kind, namespace, name)])  # Refuse missing critical runtime/state input.
    return result


def capture(root, source, output):
    expected = json.loads((root / "docs/migration/source-inventory.json").read_text())["commit"]
    actual = run(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip()
    if actual != expected: raise ValueError("source revision differs from frozen inventory")
    run(["git", "-C", str(source), "diff", "--quiet", "HEAD"])
    output = private_directory(output, (root, source))
    wrapper = ["nix", "run", "--accept-flake-config", "--no-write-lock-file", str(source) + "#matrix-access", "--"]
    stamp = {"capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "sourceCommit": actual}
    manifest = dict(stamp, complete=False, artifacts=[], counts={})
    def save(name, obj, private=False):
        payload = encrypt(root, name, dict(stamp, **obj)) if private else (json.dumps(dict(stamp, **obj), indent=2) + "\n").encode()
        manifest["artifacts"].append(write_file(output, name, payload))
    volumes = {}
    secret_objects, certificates, controller_objects, controllers = [], [], [], []
    for cluster, prefix in (("undercloud", "infrastructure"), ("services", "services")):
        def read(kind):
            return json.loads(run(wrapper + [cluster, "--", "kubectl", "--request-timeout=30s", "get", kind, "-A", "-o", "json"]))["items"]
        config = [clean_object(obj) for obj in read("secrets,configmaps")]
        secret_objects.extend({"sourceCluster": cluster, "object": obj} for obj in config)
        manifest["counts"][cluster + "_secrets_and_configmaps"] = len(config)
        if cluster == "undercloud": save("migration-state.sops.yaml", {"objects": state_inputs(config)}, private=True)
        for obj in config:
            if obj["kind"] == "Secret" and (obj.get("type") == "kubernetes.io/tls" or obj["metadata"]["name"].startswith("tfstate-") or obj["metadata"]["name"] == "letsencrypt-cloudflare-account"):
                certificates.append({"sourceCluster": cluster, "object": obj})
        for kind in ("pvc", "pv"):
            entries = [public_volume(obj) for obj in read(kind)]
            volumes[prefix + "_" + kind] = entries
            manifest["counts"][prefix + "_" + kind] = len(entries)
        entries = read(CONTROLLERS)
        controller_objects.extend({"sourceCluster": cluster, "object": clean_object(obj)} for obj in entries)
        controllers.extend({"sourceCluster": cluster, "object": public_controller(obj)} for obj in entries)
    save("source-secrets-and-config.sops.yaml", {"objects": secret_objects}, private=True)
    save("source-resources.sops.yaml", {"objects": controller_objects}, private=True)
    save("source-certificates-and-state.sops.yaml", {"objects": certificates}, private=True)
    save("live-certificate-state-inventory.json", {"objects": [certificate_record(o["sourceCluster"], o["object"]) for o in certificates]})
    save("live-volume-inventory.json", volumes)
    save("source-services-and-controllers.json", {"objects": controllers})
    cloud = json.loads(run(wrapper + ["undercloud", "--", "python3", str(Path(__file__).resolve()), "--cloud-only"]))
    save("live-cloud-volume-inventory.json", cloud["cloud"])
    save("live-address-owner-inventory.json", cloud["owners"])
    manifest["counts"].update({name: len(objects) for name, objects in cloud["cloud"].items() if name != "errors"})
    manifest["counts"]["certificate_and_state_objects"] = len(certificates)
    manifest.update(complete=True, completedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    write_file(output, "capture-manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest["counts"]


def main():
    if os.sys.argv[1:] == ["--cloud-only"]:
        print(json.dumps(collect_cloud()))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    counts = capture(args.repository_root.resolve(), args.source_repository.resolve(), args.output_directory)
    print(json.dumps({"complete": True, "readOnlySourceCapture": counts}))


if __name__ == "__main__":
    os.umask(0o077)
    try: main()
    except Exception as error:
        detail = ": " + str(error) if isinstance(error, CaptureError) else ""
        raise SystemExit("Source capture incomplete (" + type(error).__name__ + ")" + detail + "; value-bearing diagnostics suppressed. Only a final complete capture-manifest.json qualifies an output directory.") from None
