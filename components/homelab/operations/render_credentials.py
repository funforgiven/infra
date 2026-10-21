#!/usr/bin/env python3
"""Refresh concrete application Secrets from local encrypted enrollment inputs."""
import argparse
import json
import os
from pathlib import Path
import sys
import yaml
from encrypted_inputs import decrypt,values,save,secret

OIDC_APPS = ("forgejo", "grafana", "sftpgo", "navidrome", "audiomuse", "matrix", "netbird")


def identity_values(outputs):
    """Validate the complete local ToFu output before any encrypted file changes."""
    result = {}
    for app in OIDC_APPS:
        for field in ("id", "secret"):
            key = app + "_client_" + field
            item = outputs.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("value"), str) or not item["value"]:
                raise ValueError("incomplete identity outputs; diagnostics suppressed")
            result[key] = item["value"]
    return result


def replace_values(document, data):
    document.pop("data", None)
    document["stringData"] = data


def update_identity(root, outputs, update):
    current = identity_values(outputs)
    path = "deployments/homelab/cluster/apps/forge/runtime.sops.yaml"
    documents = decrypt(root / path)
    document = next(d for d in documents if d["metadata"]["name"] == "forge-runtime")
    data = values(document)
    data.update({"forgejo-oidc-client-" + field: current["forgejo_client_" + field]
                 for field in ("id", "secret")})
    replace_values(document, data)
    update(path, documents)

    path = "deployments/homelab/cluster/apps/matrix/runtime.sops.yaml"
    documents = decrypt(root / path)
    document = next(d for d in documents if d["metadata"]["name"] == "matrix-runtime")
    data = values(document)
    config = yaml.safe_load(data["mas.yaml"])
    matches = [provider for provider in config["upstream_oauth2"]["providers"]
               if provider.get("issuer", "").rstrip("/") == "https://auth.cloud.fahrican.com"]
    if len(matches) != 1:
        raise ValueError("ambiguous Matrix upstream identity; diagnostics suppressed")
    for field in ("id", "secret"):
        matches[0]["client_" + field] = current["matrix_client_" + field]
    data["mas.yaml"] = yaml.safe_dump(config, sort_keys=False)
    replace_values(document, data)
    update(path, documents)

    # NetBird owns its external identity-provider configuration through the
    # independent ToFu state, not through the server's local config.
    path = "deployments/homelab/credentials/netbird-policy/identity.sops.yaml"
    documents = decrypt(root / path)
    data = values(documents[0])
    data.update({"netbird_client_" + field: current["netbird_client_" + field]
                 for field in ("id", "secret")})
    replace_values(documents[0], data)
    update(path, documents)
    return current


def render(root,outputs=None):
    if outputs is not None:
        identity_values(outputs)
    runtime=values(decrypt(root/"secrets/service-runtime.sops.yaml")[0])
    changed=[]
    region=yaml.safe_load((root/"deployments/homelab/credentials/backup-destination.yaml").read_text())["bucket"]["region"]
    hosts_path="deployments/homelab/hosts/secrets.sops.yaml"
    hosts=decrypt(root/hosts_path)
    hosts[0]["etcd_backup_environment"]="AWS_ACCESS_KEY_ID="+runtime["B2_APPLICATION_KEY_ID"]+"\nAWS_SECRET_ACCESS_KEY="+runtime["B2_APPLICATION_KEY"]+"\nAWS_DEFAULT_REGION="+region+"\n"
    if save(root,hosts_path,hosts): changed.append(hosts_path)
    def update(relative,documents):
        if save(root,relative,documents): changed.append(relative)
    if outputs is not None:
        update_identity(root, outputs, update)
    media_path="deployments/homelab/cluster/apps/media/runtime.sops.yaml"
    media=values(decrypt(root/media_path)[0])
    keys=["ND_LASTFM_APIKEY","ND_LASTFM_SECRET","ND_PASSWORDENCRYPTIONKEY","SFTPGO_ADMIN_PASSWORD","AUDIOMUSE_NAVIDROME_PASSWORD","AUDIOMUSE_POSTGRES_PASSWORD","NAVIDROME_OAUTH2_COOKIE_SECRET","AUDIOMUSE_OAUTH2_COOKIE_SECRET"]
    media.update({k:runtime[k] for k in keys})
    if outputs is not None:
        for app in ["sftpgo","navidrome","audiomuse"]:
            for key in ["id","secret"]: media[app.upper()+"_OIDC_CLIENT_"+key.upper()]=outputs[app+"_client_"+key]["value"]
    update(media_path,[secret("media-runtime","media",media),secret("discord-music-runtime","media",{"DISCORD_TOKEN":runtime["DISCORD_MUSIC_BOT_TOKEN"],"YOUTUBE_API_KEY":runtime["DISCORD_MUSIC_YOUTUBE_API_KEY"]})])
    for app,prefix in [("factorio","FACTORIO_"),("valheim","VALHEIM_")]:
        update(f"deployments/homelab/cluster/apps/{app}/runtime.sops.yaml",[secret(app+"-runtime","games",{k:v for k,v in runtime.items() if k.startswith(prefix)})])
    update("deployments/homelab/cluster/infrastructure/velero/credentials.sops.yaml",[secret("velero-object-storage","velero",{"cloud":"[default]\naws_access_key_id="+runtime["B2_APPLICATION_KEY_ID"]+"\naws_secret_access_key="+runtime["B2_APPLICATION_KEY"]+"\n"})])
    # NetBird's Barman archive lives under Velero's services/kubernetes/ prefix
    # and uses the same B2 writer.
    update("deployments/homelab/cluster/apps/netbird/server/backup.sops.yaml",[secret("netbird-backup","netbird",{"ACCESS_KEY_ID":runtime["B2_APPLICATION_KEY_ID"],"ACCESS_SECRET_KEY":runtime["B2_APPLICATION_KEY"],"AWS_REGION":region})])
    path="deployments/homelab/cluster/infrastructure/observability/runtime.sops.yaml"
    documents=decrypt(root/path)
    telegram=next(d for d in documents if d["metadata"]["name"]=="infrastructure-telegram")
    telegram.pop("data",None);telegram["stringData"]={"bot-token":runtime["INFRA_TELEGRAM_BOT_TOKEN"]}
    alert=next(d for d in documents if d["metadata"]["name"]=="alertmanager-runtime-values")
    config=yaml.safe_load(values(alert)["values.yaml"])
    receiver=next(r for r in config["alertmanager"]["config"]["receivers"] if r["name"]=="infrastructure-telegram")
    receiver["telegram_configs"][0]["chat_id"]=int(runtime["INFRA_TELEGRAM_CHAT_ID"])
    alert.pop("data",None);alert["stringData"]={"values.yaml":yaml.safe_dump(config,sort_keys=False)}
    if outputs is not None:
        grafana = next(d for d in documents if d["metadata"]["name"] == "grafana-oidc")
        data = values(grafana)
        data.update({"GF_AUTH_GENERIC_OAUTH_CLIENT_" + field.upper(): outputs["grafana_client_" + field]["value"]
                     for field in ("id", "secret")})
        replace_values(grafana, data)
    update(path,documents)
    return changed

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root",type=Path,default=Path.cwd())
    parser.add_argument("--identity-outputs-stdin",action="store_true")
    args=parser.parse_args()
    outputs=json.load(sys.stdin) if args.identity_outputs_stdin else None
    for path in render(args.repository_root,outputs): print("Updated encrypted "+path)

if __name__=="__main__":
    os.umask(0o077)
    try: main()
    except Exception: raise SystemExit("Credential render failed; check encrypted inputs and provider output keys. Credential diagnostics suppressed.") from None
