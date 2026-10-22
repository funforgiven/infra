# Rooftrollen dashboard

`dashboard.yaml` is a YAML-mode Lovelace dashboard at
<https://home.fahrican.com/dashboard-rooftrollen/home>, and `theme.yaml` is its
light/dark theme. Both are mounted read-only from Git; edit them here, not in
the UI. Mushroom and card-mod are pinned by checksum in `../install-pinned.py`;
keep the `?v=` resource URLs in `../configuration.yaml` in step with them.

Lock controls distinguish lock, unlock and unlatch, each with a confirmation.
Nuki MQTT activity shows requests, not completed operations. To make Rooftrollen
a user's default with the system light/dark mode, set it in that user's profile.
When testing in a browser, intercept service calls so no physical lock command
is sent.
