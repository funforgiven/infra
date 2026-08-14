# Knowledge and search

Karakeep with Meilisearch is the initial personal knowledge database. Search is
strictly Karakeep full-text search; semantic retrieval, embeddings, Hindsight,
and a vector database are intentionally absent until Karakeep provides a
satisfactory native path or measured retrieval failures justify another layer.

SearXNG is a separate, disposable web-search backend for Hermes and a private
browser UI. It does not index or retrieve the Karakeep corpus. JSON output is
enabled for Hermes, and the public DNS record resolves only to the provider-LAN
load balancer. SearXNG cache state is deliberately ephemeral and excluded from
backups.

Activation remains suspended until the backup controller, schedules, storage
qualification, runtime SOPS secrets, private DNS, and an isolated Karakeep PVC
restore have all passed. Validate both a Japanese-language web query through
Hermes and a Karakeep full-text query before recording readiness.
