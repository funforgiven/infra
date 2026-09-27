# RØDECaster home controls

Two SMART pads control the Fahrican Loft light and Daikin AC from Parmigiano.
Configure each pad as **MIDI → Custom → Control Change**, **channel 16**,
**value 127**, **On only**:

| Pad label | CC | Action |
| --- | --- | --- |
| Loft light | 106 | Toggle `light.0x001788011015148f`, transition zero |
| AC airflow | 107 | Toggle vertical Comfort Airflow (`windnice`) ↔ Swing (`swing`) |

If vertical airflow is initially Stop, the first press selects Comfort Airflow.
The AC action changes only vertical airflow; power, temperature, fan speed and
horizontal direction are not part of the command. The installed Onecta
integration updates the reported vertical mode after a successful cloud write,
so another press selects the opposite mode without an extra refresh.

See RØDE's [SMART pad MIDI instructions](https://help.rode.com/hc/en-us/articles/8565481010063-MIDI-Triggers-for-R%C3%98DECaster-Pro-II-Duo).
CC 102–105 remain assigned to the existing audio-routing pads.

## Runtime

`funforgiven-home-midi.service` starts with the graphical session and subscribes
to the Duo's named ALSA MIDI input. It reconnects after USB unplug/replug. This
requires the Duo to be connected to the running PC session.

The audio-routing listener runs independently. Home commands do not inspect
window focus or need active audio. Only positive control-change messages on
channel 16 with CC 106 or 107 are accepted; releases and other pads are ignored.
Duplicate presses are suppressed for 300 ms for the bulb and 2 seconds for
airflow. Queued commands expire after 3 seconds, and failed HTTP requests are
never retried automatically because a toggle may already have happened.

```sh
systemctl --user status funforgiven-home-midi
journalctl --user -u funforgiven-home-midi -n 30
funforgiven-home-midi trigger loft-light --dry-run
funforgiven-home-midi trigger loft-airflow --dry-run
```

Omitting `--dry-run` sends the command. A submitted log message acknowledges
the HTTP request; verify device state or the HA automation trace for completion.

## Credentials and recovery

Two random webhook capabilities are SOPS encrypted in
`secrets/home-assistant-midi.yaml`. The host deploys the JSON value at
`/run/secrets/home-assistant-midi-webhooks`, owned by the user with mode `0400`.
systemd passes it using `LoadCredential`; no secret appears in command arguments
or plaintext in the Nix store.

The HA automations accept only local POST requests over the existing HTTPS
endpoint. Their target entities/actions are fixed; incoming payloads cannot
select another service. The desktop receives no general-purpose HA control
token. TLS certificate validation remains enabled and redirects are refused.
See [HA webhook documentation](https://www.home-assistant.io/docs/automation/trigger/#webhook-trigger).

Recovery templates and their installer are in
`deployments/homelab/cloud/services/25-home-automation/`:

```sh
python3 deployments/homelab/cloud/services/25-home-automation/install-rodecaster-midi.py
```

The installer needs SOPS and Python with requests/PyYAML. It renders the private
webhook IDs in memory, saves through HA's automation API, and verifies readback.
Both automations are included in the normal HA application backups. After
rotating webhook credentials, rerun the installer, rebuild NixOS and restart
the user service to refresh its credential copy.

## Verification

```sh
nix build .#checks.x86_64-linux.home-midi .#checks.x86_64-linux.audio-midi
```

Tests cover pad filtering, independent debounce, stale events, unique-device
selection, exact POST dispatch, no replay after failure, redirect rejection,
credential endpoint validation and dry runs. On September 27 the real webhook
path toggled the bulb in both directions and changed Comfort Airflow to Swing
and back. Both starting states were restored; the AC's other settings matched
their initial values.
