#!/bin/sh
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
