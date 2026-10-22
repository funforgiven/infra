# RØDECaster home controls

Two Duo SMART pads (**MIDI → Custom → Control Change**, channel 16, value 127,
On only) call Home Assistant: CC **106** toggles the loft light, CC **107**
alternates the loft Daikin's vertical Comfort Airflow (`windnice`) and Swing.
If vertical airflow is Stop, the first press selects Comfort Airflow; nothing
else on the AC changes.

`funforgiven-home-midi.service` listens on the Duo's ALSA MIDI input and
reconnects after replug. Presses are debounced (300 ms light, 2 s airflow),
queued commands expire after 3 s, and failed requests are never retried, since
a toggle may already have happened. Test with
`funforgiven-home-midi trigger loft-light --dry-run`.

The desktop holds only two webhook capabilities, not a general HA token:
`secrets/home-assistant-midi.yaml`, deployed to
`/run/secrets/home-assistant-midi-webhooks` and passed with `LoadCredential`.
The HA automations accept local POSTs only and have fixed actions. They are
installed (and covered by HA backups) with
`deployments/homelab/cluster/apps/home-automation/install-rodecaster-midi.py`;
after rotating the webhooks rerun it, rebuild, and restart the user service.
