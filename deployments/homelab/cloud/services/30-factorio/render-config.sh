#!/bin/sh
set -eu

readonly credentials=/credentials
readonly engine_config=/engine-config
readonly runtime_config=/runtime-config

cp /opt/factorio/config/config.ini "$engine_config/config.ini"
sed -i '/^write-data=/c\write-data=/factorio' "$engine_config/config.ini"

cp \
  /opt/factorio/data/map-gen-settings.example.json \
  "$runtime_config/map-gen-settings.json"
cp \
  /opt/factorio/data/map-settings.example.json \
  "$runtime_config/map-settings.json"
cp "$credentials/FACTORIO_RCON_PASSWORD" "$runtime_config/rconpw"

jq \
  --null-input \
  --rawfile username "$credentials/FACTORIO_USERNAME" \
  --rawfile token "$credentials/FACTORIO_TOKEN" \
  --rawfile game_password "$credentials/FACTORIO_GAME_PASSWORD" \
  '{
    name: "Fahrican Space Age",
    description: "A private, backed-up Space Age factory for friends.",
    tags: ["space-age", "friends", "fahrican"],
    max_players: 12,
    visibility: {
      public: true,
      lan: true
    },
    username: $username,
    token: $token,
    game_password: $game_password,
    require_user_verification: true,
    max_upload_in_kilobytes_per_second: 0,
    minimum_latency_in_ticks: 0,
    ignore_player_limit_for_returning_players: false,
    allow_commands: "admins-only",
    autosave_interval: 10,
    autosave_slots: 12,
    afk_autokick_interval: 0,
    auto_pause: true,
    only_admins_can_pause_the_game: true,
    autosave_only_on_server: true,
    non_blocking_saving: false
  }' > "$runtime_config/server-settings.json"

printf '%s\n' '[]' > "$runtime_config/server-adminlist.json"
printf '%s\n' '[]' > "$runtime_config/server-banlist.json"
printf '%s\n' '[]' > "$runtime_config/server-whitelist.json"

# Space Age, Quality, and Elevated Rails are built-in server mods. Keeping this
# list explicit prevents an image default from silently changing the world type.
install -d -m 0750 /factorio/mods
cat > /factorio/mods/mod-list.json <<'EOF'
{
  "mods": [
    { "name": "base", "enabled": true },
    { "name": "elevated-rails", "enabled": true },
    { "name": "quality", "enabled": true },
    { "name": "space-age", "enabled": true }
  ]
}
EOF

chmod 0600 "$engine_config/config.ini" "$runtime_config"/*
