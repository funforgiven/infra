# Services backup storage

This root owns the retained Cloudflare R2 bucket used by Velero and one
independent Restic bucket for Hermes, Home Assistant, and the mail edge. It
discovers the Cloudflare account through the already-managed `fahrican.com`
zone, so the only activation input is an API token with zone-read and
R2-bucket-edit access.

It deliberately does not create R2 S3 access keys: Cloudflare returns those
secret values only at issuance time, which would persist them in OpenTofu
state. Issue one key per bucket with the narrowest supported object
permissions. Enroll the services-cluster key directly into the SOPS bootstrap
Secret and stream each host key into only that host's root-only Restic files.

Velero owns object expiry through its backup TTLs. No bucket lifecycle rule may
expire the newest recovery point merely because the cluster stopped uploading.
