{ config, lib, ... }:
let
  hostName = "parmigiano";
  hostModel = config.dendritic.hosts.${hostName};
in
{
  perSystem =
    { pkgs, system, ... }:
    let
      shellConfigName = config.dendritic.quickshell.configName;
      nativeHostModel = lib.recursiveUpdate hostModel {
        polkit.agent = "quickshell";
      };
      nativeHostEvaluation = config.dendritic.builders.mkNixosConfiguration hostName nativeHostModel;
      nativeHomeEvaluation = config.dendritic.builders.mkHomeConfiguration hostName nativeHostModel;
      nativeHostConfig = nativeHostEvaluation.config;
      nativeHomeConfig = nativeHomeEvaluation.config;
      nativeShellConfig = nativeHomeConfig.programs.quickshell.configs.${shellConfigName};
      nativeQuickshell = nativeHomeConfig.programs.quickshell.package;
    in
    {
      checks = lib.mkIf (system == hostModel.system) {
        quickshell-native-polkit-home = nativeHomeEvaluation.activationPackage;
        quickshell-native-polkit-toplevel = nativeHostConfig.system.build.toplevel;

        quickshell-native-polkit-smoke =
          pkgs.runCommandLocal "quickshell-native-polkit-smoke"
            {
              nativeBuildInputs = [
                nativeQuickshell
                pkgs.coreutils
                pkgs.gnugrep
                pkgs.weston
              ];
            }
            ''
              set -euo pipefail

              export HOME="$TMPDIR/home"
              export XDG_CACHE_HOME="$TMPDIR/cache"
              export XDG_RUNTIME_DIR="$TMPDIR/runtime"
              export LC_ALL=C.UTF-8
              export XDG_DATA_DIRS="${nativeHomeConfig.home.path}/share:${nativeHostConfig.system.path}/share"
              export XDG_CURRENT_DESKTOP=niri
              export QT_QPA_PLATFORM=wayland
              export QT_QUICK_BACKEND=software
              export WAYLAND_DISPLAY=wayland-native-polkit-smoke
              export NIRI_SOCKET="$TMPDIR/niri-missing.sock"
              export QS_DISABLE_FILE_WATCHER=1
              export QS_NO_RELOAD_POPUP=1
              export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$TMPDIR/no-system-bus"
              export DBUS_SESSION_BUS_ADDRESS="unix:path=$TMPDIR/no-session-bus"
              mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR"
              chmod 0700 "$XDG_RUNTIME_DIR"

              weston \
                --backend=headless \
                --renderer=pixman \
                --shell=kiosk \
                --socket="$WAYLAND_DISPLAY" \
                --idle-time=0 \
                --width=1920 \
                --height=1080 \
                --no-config \
                --log="$TMPDIR/weston.log" &
              weston_pid=$!
              trap 'kill "$weston_pid" 2>/dev/null || true' EXIT

              for attempt in $(seq 1 100); do
                [[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] && break
                sleep 0.05
              done
              if [[ ! -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]]; then
                cat "$TMPDIR/weston.log" >&2
                exit 1
              fi

              set +e
              timeout --signal=TERM --kill-after=2s 10s \
                qs --no-color -v -p ${nativeShellConfig} \
                >"$TMPDIR/quickshell.log" 2>&1
              qs_status=$?
              set -e

              if [[ "$qs_status" -ne 124 ]] \
                || ! grep -Fq 'Configuration Loaded' "$TMPDIR/quickshell.log"; then
                cat "$TMPDIR/quickshell.log" >&2
                cat "$TMPDIR/weston.log" >&2
                exit 1
              fi
              if grep -Eq \
                'Failed to load configuration|Invalid property assignment| is not a type|TypeError|ReferenceError|Binding loop detected|Cannot read property [^ ]+ of null|Cannot anchor to an item' \
                "$TMPDIR/quickshell.log"; then
                cat "$TMPDIR/quickshell.log" >&2
                exit 1
              fi

              kill "$weston_pid" 2>/dev/null || true
              wait "$weston_pid" 2>/dev/null || true
              trap - EXIT
              touch "$out"
            '';
      };
    };
}
