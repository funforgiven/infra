# Hermes OpenAI control plane

This OpenTofu root owns the dedicated Hermes production project, nonhuman
service account, custom role, group-based role assignment, Luna-only model
allowlist, all-disabled hosted-tool policy, and USD 50 monthly hard spend
limit. It uses the official
`openai/openai` provider pinned by version and lock file.

The service account deliberately receives no built-in member or owner role.
Its custom role contains only `api.responses.write`, matching Hermes's
Responses API use. OpenAI hosted tools are explicitly disabled: web search uses
the local SearXNG service, Karakeep is local MCP, and semantic retrieval is
deferred. OpenAI requires its organization-level policy for each tool to be
`deny all` or `selected projects` before a project can declare `false`; the
conditional credential-final check is documented as a manual exception because
the Administration API does not expose organization-level tool policy.

`OPENAI_ADMIN_KEY` authenticates the provider through the environment only
during an explicit maintenance window. It is an ephemeral bootstrap
credential, not a Hermes runtime credential. API-key material is excluded from
this root and its state because OpenAI returns a service-account key value only
once. After this root applies, the pinned `reconcile-services-openai` app issues
the scoped key directly into the admin-only Hermes SOPS document. Its guarded
`retire-admin` command verifies that key, the Luna allowlist, every hosted-tool
deny, and the USD 50 hard limit before revoking the named Admin key and removing
its ciphertext. The Terraform reconciliation is then suspended until a future
maintenance window enrolls a new temporary Admin key.
