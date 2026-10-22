#!/bin/sh
# Recover the production Barman archive into a disposable cluster, check it and
# delete it. The restore cluster has no WAL archiver or backup configuration.
set -eu
cleanup() {
  kubectl delete cluster.postgresql.cnpg.io restore --ignore-not-found --wait=true --timeout=10m
  kubectl delete secret source-credentials --ignore-not-found
}
trap cleanup EXIT
cleanup
kubectl -n "$SOURCE_NAMESPACE" get secret "$SOURCE_SECRET" -o json |
  jq '{apiVersion, kind, type, data, metadata: {name: "source-credentials"}}' |
  kubectl create -f -
jq --arg server "$SERVER_NAME" --arg size "$STORAGE_SIZE" \
  '.spec.externalClusters[0].plugin.parameters.serverName = $server | .spec.storage.size = $size' \
  /restore/cluster.json | kubectl create -f -
kubectl wait cluster.postgresql.cnpg.io/restore --for=condition=Ready --timeout=60m
primary="$(kubectl get cluster.postgresql.cnpg.io restore -o jsonpath='{.status.currentPrimary}')"
kubectl exec -i "$primary" -c postgres -- psql -X -q -v ON_ERROR_STOP=1 -f - </restore/check.sql
echo "Recovered $SOURCE_NAMESPACE PostgreSQL passed its checks"
