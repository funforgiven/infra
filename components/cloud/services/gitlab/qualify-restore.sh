#!/usr/bin/env bash
# Restore into a separately prepared, network-isolated recovery namespace.
# Never run against production. See deployments/homelab/cloud/gitlab/RECOVERY.md.
set -euo pipefail
umask 077
[[ $# -eq 3 ]] || { echo 'Usage: qualify-restore.sh RECOVERY_CONTEXT BACKUP_ID REPORT_DIRECTORY' >&2; exit 64; }
context=$1
backup_id=$2
report=$(realpath "$3")
[[ "$backup_id" =~ ^[0-9]{10}_[0-9]{4}_[0-9]{2}_[0-9]{2}_19\.3\.1-ee$ ]]
[[ -d "$report" && ! -e "$report/restore.prom" ]]
k=(kubectl --context "$context" --namespace gitlab-recovery)
"${k[@]}" get namespace gitlab-recovery -o json | jq -e '
  .metadata.labels["infra.fahrican.com/purpose"] == "gitlab-recovery"
' >/dev/null
"${k[@]}" get helmrelease gitlab -o json | jq -e '.spec.suspend == true' >/dev/null
"${k[@]}" get networkpolicies -o json > "$report/network-policies.json"
# Require a namespace-wide egress policy and reject every policy that allows
# external IPs or arbitrary namespaces. DNS is the only cross-namespace peer.
jq -e '
  any(.items[]; .spec.podSelector == {} and (.spec.policyTypes | index("Egress"))) and
  all(.items[].spec.egress[]?;
    has("to") and (.to | length > 0) and
    all(.to[];
      (has("podSelector") and (has("namespaceSelector") | not) and (has("ipBlock") | not)) or
      (.namespaceSelector.matchLabels["kubernetes.io/metadata.name"] == "kube-system" and
       .podSelector.matchLabels["k8s-app"] == "kube-dns" and (has("ipBlock") | not))))
' "$report/network-policies.json" >/dev/null
"${k[@]}" get pods -o json | jq -e '
  all(.items[];
    (.spec.hostNetwork != true and .spec.hostPID != true and .spec.hostIPC != true) and
    all(.spec.volumes[]?; has("hostPath") | not) and
    all((.spec.containers + (.spec.initContainers // []))[];
      .securityContext.privileged != true))
' >/dev/null
# Configuration must name the recovery instance. Mail, hooks and external
# integrations remain blocked by egress policy throughout the exercise.
"${k[@]}" exec deployment/gitlab-toolbox -- gitlab-rails runner \
  'abort "Unexpected recovery host" unless Gitlab.config.gitlab.host == "gitlab-restore.invalid"'
"${k[@]}" scale deployment gitlab-webservice-default gitlab-sidekiq-all-in-1-v2 --replicas=0
# Expanded by the shell inside the recovery toolbox.
# shellcheck disable=SC2016
"${k[@]}" exec deployment/gitlab-toolbox -- /bin/bash -ec \
  'cp /etc/gitlab/.s3cfg "$HOME/.s3cfg"; backup-utility --restore --skip-restore-prompt -t "$1"' -- "$backup_id"
"${k[@]}" exec deployment/gitlab-toolbox -- gitlab-rake gitlab:check SANITIZE=true
"${k[@]}" exec deployment/gitlab-toolbox -- gitlab-rake gitlab:doctor:secrets
"${k[@]}" exec deployment/gitlab-toolbox -- gitlab-rake \
  gitlab:artifacts:check gitlab:lfs:check gitlab:uploads:check
printf '%s\n' "$backup_id" > "$report/backup-id"
printf 'gitlab_restore_last_success_unixtime %s\n' "$(date +%s)" > "$report/restore.prom"
echo 'Native restore and integrity checks passed in the isolated recovery namespace.'
echo 'Review logs and verify repository clones and registry pulls before publishing the success metric.'
