#!/bin/sh
set -eu
umask 077

navidrome=/app/navidrome
config_dir=/tmp/navidrome-plugin-config
mkdir -p "$config_dir"

printf '%s\n' \
  '{"apiUrl":"http://audiomuse-api.media.svc.cluster.local:8000","apiToken":"","server":"Navidrome","artistSimilarCount":10,"eliminateDuplicates":true,"radiusSimilarity":true}' \
  > "$config_dir/audiomuseai.json"
cat > "$config_dir/nd-lyrics.json" <<'JSON'
{
  "lyricsFormats": "lrc,elrc,ttml,srt,plain",
  "providersList": [{"provider": "lrclib"}],
  "providerMode": "sync",
  "preferUncensored": false,
  "enableCache": true,
  "perTypeCacheTtl": false,
  "cacheTtlHours": 168,
  "negativeCache": true,
  "negativeCacheTtlHours": 24,
  "writeLyrics": false,
  "overwriteLyrics": false,
  "writeToSpecificFolder": false
}
JSON

"$navidrome" plugin validate /data/plugins/audiomuseai.ndp
"$navidrome" plugin validate /data/plugins/nd-lyrics.ndp
"$navidrome" plugin rescan
"$navidrome" plugin edit audiomuseai \
  --config-file "$config_dir/audiomuseai.json" \
  --all-users --all-libraries --no-write-access
"$navidrome" plugin edit nd-lyrics \
  --config-file "$config_dir/nd-lyrics.json" \
  --all-users --all-libraries --no-write-access
"$navidrome" plugin enable audiomuseai
"$navidrome" plugin enable nd-lyrics
