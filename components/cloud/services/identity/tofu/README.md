# Services identity

This state is intentionally separate from the main identity state. It can emit
only the Karakeep client ID and secret, which lets the services-cluster
bootstrap controller receive the minimum OIDC material without access to the
Grafana, OpenStack, or ZITADEL controller credentials.
