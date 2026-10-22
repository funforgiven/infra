#!/bin/bash
set -euo pipefail

exec /usr/local/bin/supervisord -n -c /bootstrap/supervisord.conf
