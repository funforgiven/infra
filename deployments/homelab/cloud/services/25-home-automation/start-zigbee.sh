#!/bin/sh
set -eu
if test "$ZIGBEE_ENABLED" != true; then
  echo 'Zigbee radio is disabled until its fixed coordinator address is configured.'
  exec sleep infinity
fi
export ZIGBEE2MQTT_CONFIG_SERIAL_PORT="$ZIGBEE_SERIAL_PORT"
export ZIGBEE2MQTT_CONFIG_ADVANCED_CHANNEL="$ZIGBEE_CHANNEL"
export ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD
ZIGBEE2MQTT_CONFIG_MQTT_PASSWORD="$(cat /credentials/zigbee2mqtt-password)"
export ZIGBEE2MQTT_CONFIG_FRONTEND_AUTH_TOKEN
ZIGBEE2MQTT_CONFIG_FRONTEND_AUTH_TOKEN="$(cat /credentials/zigbee-ui-token)"
exec node /app/index.js
