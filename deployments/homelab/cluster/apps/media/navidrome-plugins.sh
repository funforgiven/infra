#!/bin/sh
# Install checksum-pinned Navidrome plugins, then configure and enable them.
set -eu
umask 077

plugin_dir=/data/plugins
mkdir -p "$plugin_dir"

install_plugin() {
  name="$1"
  url="$2"
  expected="$3"
  destination="$plugin_dir/$name.ndp"

  if [ -f "$destination" ] && \
    printf '%s  %s\n' "$expected" "$destination" | sha256sum -c - >/dev/null 2>&1; then
    printf '%s is already checksum-verified\n' "$name"
    return
  fi

  temporary="$destination.download"
  rm -f "$temporary"
  wget -q -O "$temporary" "$url"
  printf '%s  %s\n' "$expected" "$temporary" | sha256sum -c -
  mv "$temporary" "$destination"
}

install_plugin \
  audiomuseai \
  https://github.com/NeptuneHub/AudioMuse-AI-NV-plugin/releases/download/v9/audiomuseai.ndp \
  bca0b84ab29359f364a645fba968c4574b9bc81ef58c6f33d03957ae33b50cfc
install_plugin \
  nd-lyrics \
  https://github.com/J0R6IT0/navidrome-lyrics-plugin/releases/download/v7.2.0/nd-lyrics.ndp \
  a9196e5b4e2c2eb2aaccb9f35c9faf6f488fe9081ff5685b1556901686c7540f

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
