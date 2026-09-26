# Rooftrollen dashboard

Open <https://home.fahrican.com/dashboard-rooftrollen/home>.

The dashboard groups everyday controls by room and floor, with separate Lights,
Climate and Door pages. Room headings open detail pages. The six populated rooms
are shown; adding an unassigned device does not put its diagnostic entities on
the home page. Fahrican Spare Room is on the **5th floor**; the bathroom relay is
in **Fahrican Bathroom** on the **6th floor**.

## Design and behavior

- Native Sections layout: three columns on a large screen, one on a phone.
- The Rooftrollen theme has both light and dark palettes. The owner's theme
  preference omits `dark`, which means follow the operating system, rather than
  forcing either mode. The same account's dashboard preference opens Rooftrollen.
- Room colors remain consistent between the home page and detailed controls.
  Light controls use amber when on so white bulbs remain visibly active.
- Tap a light to switch it; use its slider for brightness. Open a room or the
  Lights page for color and color-temperature controls. Existing Zigbee2MQTT
  transition-zero/native Hue settings continue to govern these commands.
- The light count includes the bathroom relay. The explicitly labeled group-off
  button turns off the **five Hue bulbs**, keeping the bathroom presence workflow
  independent. This button sends `light.turn_off` with `transition: 0`.
- Climate shows the loft Daikin thermostat, bathroom temperature/humidity and
  history, outdoor weather, and the AC's reported cooling electricity use. These
  cards use existing integration data and do not change Onecta polling.
- Door status comes from the existing Matter lock. Lock, unlock and unlatch are
  distinct controls and all have confirmation prompts. The activity card uses
  the existing Matter state and Nuki MQTT event; requested events do not prove
  that a physical operation completed. A locked state does not prove the door
  leaf is closed.
- Automation cards open more-info; they do not invoke an automation action when
  tapped. Existing dimmer, keypad and presence automations are unchanged.

The layout takes inspiration from
[Mushroom](https://github.com/piitaya/lovelace-mushroom) and
[Adaptive Mushroom](https://github.com/sga-noud/adaptive-mushroom). It uses native
Home Assistant navigation and cards together with Mushroom and card-mod. No
HACS integration, external font service or remotely hosted runtime card is needed.

## Ownership and backup

`dashboard.yaml` is the reviewed recovery source. The live dashboard remains in
Home Assistant storage mode and can be edited in its UI. Export intentional UI
edits back to this file before running the installer, which explicitly replaces
this dashboard's live configuration with the recovery source. Flux does not
continually overwrite dashboard edits.

`theme.yaml` is installed at `/config/themes/rooftrollen.yaml`. Frontend assets
are installed under `/config/www/rooftrollen/`; versions, upstream URLs and SHA-256
checksums are pinned in `assets.json`. Mushroom uses Apache-2.0; card-mod uses MIT.
The compiled assets are fetched from their tagged upstream releases, verified
before installation and checked again through Home Assistant's HTTPS endpoint.
Assets are served locally after installation; normal operation and restarts do
not download them again.

The existing application backup already includes the dashboard's `.storage`
configuration, theme, local assets and user preferences. Installation also saves
the previous frontend files/configuration under
`/config/.dashboard-backups/<UTC timestamp>/`. These files live on the same state
PVC and are included in application recovery archives.

## Install or recover

Run from the repository root with a services-cluster kubeconfig and Python that
provides **PyYAML, requests and websocket-client**. `kubectl` and `sops` must be
available on PATH (or supplied with `--kubectl` and `--sops`).

```sh
python3 deployments/homelab/cloud/services/25-home-automation/dashboard/install.py \
  --kubeconfig /path/to/services-kubeconfig \
  --credentials secrets/home-assistant.yaml \
  --set-user-default
```

The installer decrypts the existing HA token in memory, validates entity
references, checks downloaded assets, and saves a recovery copy before changing
frontend files. It preserves unrelated dashboards/resources. If `frontend` is
already customized with a different theme include, it stops rather than
overwriting that configuration; merge the named theme into the existing include
before proceeding.

`--set-user-default` changes only the token owner's dashboard and theme
preferences. Omit it to install the dashboard without changing preferences.
The installer merges other preference fields and removes the explicit `dark`
field to follow the system setting.

On the first installation, if `/config/www` did not exist when HA started, HA
must restart once to register the `/local` route. The installer reports this
condition after writing the checked files. Restart **Home Assistant** through
Settings → System, then rerun the installer. Later dashboard edits and theme
reloads need no restart. The initial installation used one graceful HA restart;
the MQTT, Zigbee, Matter and OTBR processes were not restarted.

For dashboard-only edits, save parsed `dashboard.yaml` through the authenticated
WebSocket command `lovelace/config/save` with
`url_path: dashboard-rooftrollen`. For theme edits, update the theme file and call
`frontend.reload_themes`. Do not edit live `.storage` files behind HA's back.

## Verification

Initial validation on 2026-09-26 covers:

- Home Assistant configuration check and exact dashboard/theme API readback.
- All referenced entities exist; local resource checksums match their pins.
- Authenticated Chromium renders at desktop and phone widths in light and dark.
- Live system color-mode changes, default-dashboard routing and room navigation.
- Light dispatch and separate lock/unlock/unlatch mappings, with service calls
  intercepted inside the test browser. No physical lock command is sent by UI
  tests. Confirmation prompts and cancellation are checked independently.

Keep validation screenshots and temporary browser credentials out of Git. Browser
checks use the existing encrypted token in memory and do not record its value.
