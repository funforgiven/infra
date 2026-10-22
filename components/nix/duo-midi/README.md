# RØDECaster Duo pads

`funforgiven-duo-midi.service` listens on the Duo's ALSA MIDI input, reconnects
after replug, and hands each pad press to the module that owns its CC. Configure
the SMART pads as **MIDI → Custom → Control Change**, channel **16**, value
**127**, **On only** (enable MIDI under Settings → System → MIDI).

| CC | Action | Module |
| --- | --- | --- |
| 102–105 | Move the focused app to System / Game / Voice Chat / Music | `audio.py` |
| 106 | Toggle the loft light | `home.py` |
| 107 | Alternate the loft Daikin's vertical Comfort Airflow (`windnice`) and Swing | `home.py` |

Audio and home pads have separate queues and workers, so a slow move never
delays a toggle and vice versa. Test without hardware effects using
`sleep 3; funforgiven-duo-midi route game --dry-run` or
`funforgiven-duo-midi trigger loft-light --dry-run`.

## Audio routing

The focused Niri app is captured when the press arrives, and all of its live
playback streams move (browsers count as one app) through
`funforgiven-audioctl move-stream`, which WirePlumber then remembers per app;
see [audio channels](../audio-channels/README.md). An app must already be
playing. Window titles are never used, and a window launched from the focused
terminal is not treated as the terminal's audio.

## Home controls

If vertical airflow is Stop, the first CC 107 press selects Comfort Airflow;
nothing else on the AC changes. Presses are debounced (300 ms light, 2 s
airflow), queued commands expire after 3 s, and failed requests are never
retried, since a toggle may already have happened. Errors never log the URL.

The desktop holds only two webhook capabilities, not a general HA token:
`secrets/home-assistant-midi.yaml`, deployed to
`/run/secrets/home-assistant-midi-webhooks` and passed with `LoadCredential`.
If that credential is missing or invalid, the service logs an error and keeps
routing audio with the home pads disabled. The HA automations accept local
POSTs only and have fixed actions. They are installed (and covered by HA
backups) with
`deployments/homelab/cluster/apps/home-automation/install-rodecaster-midi.py`;
after rotating the webhooks rerun it, rebuild, and restart the user service.
