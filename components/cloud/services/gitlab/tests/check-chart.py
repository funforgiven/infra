#!/usr/bin/env python3
"""Validate the rendered upstream charts, including Flux's backup post-renderer."""
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

repo, chart = (Path(value).resolve() for value in sys.argv[1:])
base = repo / "deployments/homelab/cloud/gitlab"
release = list(yaml.safe_load_all((base / "30-application/gitlab.yaml").read_text()))[1]["spec"]
runner = list(yaml.safe_load_all((base / "40-runners/runner.yaml").read_text()))[1]["spec"]
with tempfile.TemporaryDirectory() as directory:
    work = Path(directory)
    for name, spec, source, namespace in [
        ("gitlab", release, chart, "gitlab"),
        ("runner", runner, chart / "charts/gitlab-runner", "gitlab-runners"),
    ]:
        values = work / f"{name}-values.yaml"
        values.write_text(yaml.safe_dump(spec["values"]))
        rendered = subprocess.check_output([
            "helm", "template", name, str(source), "-n", namespace,
            "--kube-version", "1.36.2", "-f", str(values),
        ])
        if spec.get("postRenderers"):
            (work / "rendered.yaml").write_bytes(rendered)
            renderer = spec["postRenderers"][0]["kustomize"]
            (work / "kustomization.yaml").write_text(yaml.safe_dump({
                "apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                "resources": ["rendered.yaml"], **renderer,
            }))
            rendered = subprocess.check_output(["kustomize", "build", str(work)])
        docs = [d for d in yaml.safe_load_all(rendered) if d]
        def check_images(value):
            if isinstance(value, dict):
                if isinstance(value.get("image"), str):
                    assert "@sha256:" in value["image"], value["image"]
                for child in value.values():
                    check_images(child)
            elif isinstance(value, list):
                for child in value:
                    check_images(child)
        check_images(docs)
        assert not any(d["kind"] in {"Ingress", "StatefulSet"} for d in docs), name
        assert all(d["spec"].get("type", "ClusterIP") == "ClusterIP"
                   for d in docs if d["kind"] == "Service"), name
        if name == "gitlab":
            services = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Service"}
            routes = yaml.safe_load_all((base / "36-routes/routes.yaml").read_text())
            for route in routes:
                if route["kind"] not in {"HTTPRoute", "TCPRoute"}:
                    continue
                for rule in route["spec"]["rules"]:
                    for ref in rule.get("backendRefs", []):
                        ports = services[ref["name"]]["spec"]["ports"]
                        assert ref["port"] in [p["port"] for p in ports], ref
            cron = next(d for d in docs if d["kind"] == "CronJob"
                        and d["metadata"]["name"] == "gitlab-toolbox-backup")
            assert cron["spec"]["concurrencyPolicy"] == "Forbid"
            pod = cron["spec"]["jobTemplate"]["spec"]["template"]
            assert pod["metadata"]["labels"]["gitlab-backup"] == "true"
            assert pod["spec"]["serviceAccountName"] == "gitlab-recovery"
            assert any(c["name"] == "capture-recovery-secrets" for c in pod["spec"]["initContainers"])
            command = pod["spec"]["containers"][0]["args"][-1]
            assert command.index('backup-utility -t "$id"') < command.index('${id}_complete')
            assert 's3://gitlab-backups/${id}_secrets.json' in command
            mounts = pod["spec"]["containers"][0]["volumeMounts"]
            assert any(m["name"] == "recovery" for m in mounts)
            assert release["values"]["global"]["edition"] == "ee"
            assert not release["values"]["global"].get("license")
        else:
            deployment = next(d for d in docs if d["kind"] == "Deployment")
            pod = deployment["spec"]["template"]["spec"]
            assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
            assert pod["serviceAccountName"] == "gitlab-runner-manager"
            assert not any(d["kind"] == "ClusterRole" for d in docs)
print("GitLab and runner chart rendering, route backends, RBAC and paired backup validation passed.")
