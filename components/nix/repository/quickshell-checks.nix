{ config, lib, ... }:
{
  perSystem =
    { pkgs, system, ... }:
    let
      host = config.flake.nixosConfigurations.parmigiano;
      userName = config.users.${config.dendritic.hosts.parmigiano.user}.username;
      shellConfigName = config.dendritic.quickshell.configName;
      hostConfig = host.config;
      homeConfig = hostConfig.home-manager.users.${userName};
      shellConfig = homeConfig.programs.quickshell.configs.${shellConfigName};
      quickshell = homeConfig.programs.quickshell.package;
      materialPalette = homeConfig.stylix.base16Scheme.x-material-you-json;

      # The alternate generation selecting the native Quickshell polkit agent.
      nativeHostConfig =
        (host.extendModules {
          modules = [ { dendritic.polkit.agent = lib.mkForce "quickshell"; } ];
        }).config;
      nativeHomeConfig = nativeHostConfig.home-manager.users.${userName};
      nativeShellConfig = nativeHomeConfig.programs.quickshell.configs.${shellConfigName};

      # Starts a headless Weston session for a Quickshell smoke test.
      westonSession = hostConfig: homeConfig: socket: ''
        set -euo pipefail

        export HOME="$TMPDIR/home"
        export XDG_CACHE_HOME="$TMPDIR/cache"
        export XDG_RUNTIME_DIR="$TMPDIR/runtime"
        export LC_ALL=C.UTF-8
        export XDG_DATA_DIRS="${homeConfig.home.path}/share:${hostConfig.system.path}/share"
        export XDG_CURRENT_DESKTOP=niri
        export QT_QPA_PLATFORM=wayland
        export QT_QUICK_BACKEND=software
        export WAYLAND_DISPLAY=${socket}
        export NIRI_SOCKET="$TMPDIR/niri-missing.sock"
        export QS_DISABLE_FILE_WATCHER=1
        export QS_NO_RELOAD_POPUP=1
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
        qs_pid=
        cleanup() {
          if [[ -n "$qs_pid" ]]; then
            kill "$qs_pid" 2>/dev/null || true
            wait "$qs_pid" 2>/dev/null || true
          fi
          kill "$weston_pid" 2>/dev/null || true
          wait "$weston_pid" 2>/dev/null || true
        }
        trap cleanup EXIT

        for attempt in $(seq 1 100); do
          [[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] && break
          sleep 0.05
        done
        if [[ ! -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]]; then
          cat "$TMPDIR/weston.log" >&2
          exit 1
        fi
      '';
      failOnQmlErrors = ''
        if grep -Eq \
          'Failed to load configuration|Invalid property assignment| is not a type|TypeError|ReferenceError|Binding loop detected|Cannot read property [^ ]+ of null|Cannot anchor to an item' \
          "$TMPDIR/quickshell.log"; then
          cat "$TMPDIR/quickshell.log" >&2
          exit 1
        fi
      '';

      quickshellRuntimeContracts = quickshell.overrideAttrs (previous: {
        cmakeFlags = (previous.cmakeFlags or [ ]) ++ [
          "-DBUILD_TESTING=ON"
          "-DCRASH_HANDLER=OFF"
          "-DUSE_JEMALLOC=OFF"
          "-DWAYLAND=OFF"
          "-DX11=OFF"
          "-DI3=OFF"
          "-DSERVICE_STATUS_NOTIFIER=OFF"
          "-DSERVICE_PIPEWIRE=OFF"
          "-DSERVICE_MPRIS=OFF"
          "-DSERVICE_PAM=OFF"
          "-DSERVICE_POLKIT=OFF"
          "-DSERVICE_GREETD=OFF"
          "-DSERVICE_UPOWER=OFF"
          "-DSERVICE_NOTIFICATIONS=OFF"
          "-DBLUETOOTH=OFF"
          "-DNETWORK=OFF"
        ];
        doCheck = true;
        checkPhase = ''
          runHook preCheck
          export QT_QPA_PLATFORM=offscreen
          ctest --output-on-failure --no-tests=error -R '^datastream$'
          ctest --output-on-failure --no-tests=error -R '^socketreconnect$'
          ./src/window/test/popupwindow clearAnchorItem
          runHook postCheck
        '';
      });
      desktopEntryProbeQml = pkgs.writeText "shell.qml" ''
        //@ pragma UseQApplication

        import QtQuick
        import Quickshell
        import "." as Generated

        ShellRoot {
            id: root

            readonly property var requiredIds: Generated.ShellConfig.pinnedDesktopIds

            function failures() {
                var result = [];
                for (var index = 0; index < root.requiredIds.length; index += 1) {
                    var id = root.requiredIds[index];
                    var entry = DesktopEntries.byId(id);
                    if (entry === null) {
                        result.push(id + ": missing");
                    } else if (!entry.command || entry.command.length === 0) {
                        result.push(id + ": no command");
                    } else if (!entry.icon || entry.icon.length === 0) {
                        result.push(id + ": no icon");
                    }
                }
                return result;
            }

            function validate() {
                var problems = root.failures();
                if (problems.length === 0) {
                    console.log("Desktop-entry contract passed for " + root.requiredIds.join(", "));
                    Qt.exit(0);
                }
            }

            Connections {
                target: DesktopEntries
                function onApplicationsChanged() {
                    root.validate();
                }
            }

            Timer {
                interval: 5000
                running: true
                onTriggered: {
                    console.error("Desktop-entry contract failed: " + root.failures().join("; "));
                    Qt.exit(1);
                }
            }

            Component.onCompleted: Qt.callLater(root.validate)
        }
      '';
      desktopEntryProbeQmldir = pkgs.writeText "qmldir" ''
        singleton ShellConfig 1.0 ShellConfig.qml
      '';
      desktopEntryProbe = pkgs.runCommandLocal "quickshell-desktop-entry-probe-source" { } ''
        mkdir -p "$out"
        install -m 0444 ${desktopEntryProbeQml} "$out/shell.qml"
        install -m 0444 ${desktopEntryProbeQmldir} "$out/qmldir"
        ln -s ${shellConfig}/generated/ShellConfig.qml "$out/ShellConfig.qml"
      '';
      qtQmlPaths = [
        "${shellConfig}"
        "${pkgs.qt6.qtdeclarative}/lib/qt-6/qml"
        "${pkgs.qt6.qtwayland}/lib/qt-6/qml"
        "${quickshell}/lib/qt-6/qml"
      ];
      qmlImportArgs = builtins.concatMap (path: [
        "-I"
        path
      ]) qtQmlPaths;
      scannerImportArgs = builtins.concatMap (path: [
        "-importPath"
        path
      ]) qtQmlPaths;
      testImportArgs = builtins.concatMap (path: [
        "-import"
        path
      ]) qtQmlPaths;
    in
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        quickshell-runtime-contracts = quickshellRuntimeContracts;

        quickshell-runtime-smoke =
          pkgs.runCommandLocal "quickshell-runtime-smoke"
            {
              nativeBuildInputs = [
                quickshell
                pkgs.coreutils
                pkgs.gnugrep
                pkgs.weston
              ];
            }
            ''
              ${westonSession hostConfig homeConfig "wayland-smoke"}

              qs --no-color -v -p ${shellConfig} \
                >"$TMPDIR/quickshell.log" 2>&1 &
              qs_pid=$!

              loaded=false
              for attempt in $(seq 1 120); do
                if ! kill -0 "$qs_pid" 2>/dev/null; then
                  break
                fi
                if grep -Fq 'Configuration Loaded' "$TMPDIR/quickshell.log"; then
                  loaded=true
                  break
                fi
                sleep 0.05
              done
              if [[ "$loaded" != true ]]; then
                cat "$TMPDIR/quickshell.log" >&2
                cat "$TMPDIR/weston.log" >&2
                exit 1
              fi

              ipc_ready=false
              for attempt in $(seq 1 100); do
                set +e
                initial_state="$(qs ipc --pid "$qs_pid" call launcher isVisible 2>"$TMPDIR/ipc-error.log")"
                ipc_status=$?
                set -e
                if [[ "$ipc_status" -eq 0 ]]; then
                  ipc_ready=true
                  break
                fi
                sleep 0.05
              done
              if [[ "$ipc_ready" != true ]] || [[ "$initial_state" != false ]]; then
                cat "$TMPDIR/ipc-error.log" >&2
                echo "Launcher IPC did not become ready and closed; state=$initial_state" >&2
                exit 1
              fi

              qs ipc --pid "$qs_pid" call launcher open >/dev/null
              open_state="$(qs ipc --pid "$qs_pid" call launcher isVisible)"
              if [[ "$open_state" != true ]]; then
                echo "Launcher failed to open through IPC; state=$open_state" >&2
                exit 1
              fi

              qs ipc --pid "$qs_pid" call launcher close >/dev/null
              closed_state="$(qs ipc --pid "$qs_pid" call launcher isVisible)"
              if [[ "$closed_state" != false ]]; then
                echo "Launcher failed to close through IPC; state=$closed_state" >&2
                exit 1
              fi

              qs ipc --pid "$qs_pid" call launcher open >/dev/null
              qs ipc --pid "$qs_pid" call camera open >/dev/null
              camera_state="$(qs ipc --pid "$qs_pid" call camera isVisible)"
              launcher_state="$(qs ipc --pid "$qs_pid" call launcher isVisible)"
              if [[ "$camera_state" != true ]] || [[ "$launcher_state" != false ]]; then
                echo "Camera popup did not take ownership; camera=$camera_state launcher=$launcher_state" >&2
                exit 1
              fi
              qs ipc --pid "$qs_pid" call camera snapshot >/dev/null
              qs ipc --pid "$qs_pid" call camera close >/dev/null
              if [[ "$(qs ipc --pid "$qs_pid" call camera isVisible)" != false ]]; then
                echo "Camera popup failed to close through IPC" >&2
                exit 1
              fi

              if ! kill -0 "$qs_pid" 2>/dev/null; then
                cat "$TMPDIR/quickshell.log" >&2
                exit 1
              fi
              ${failOnQmlErrors}

              cleanup
              trap - EXIT
              touch "$out"
            '';

        quickshell-native-polkit-home = nativeHomeConfig.home.activationPackage;
        quickshell-native-polkit-toplevel = nativeHostConfig.system.build.toplevel;
        quickshell-native-polkit-smoke =
          pkgs.runCommandLocal "quickshell-native-polkit-smoke"
            {
              nativeBuildInputs = [
                nativeHomeConfig.programs.quickshell.package
                pkgs.coreutils
                pkgs.gnugrep
                pkgs.weston
              ];
            }
            ''
              export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$TMPDIR/no-system-bus"
              export DBUS_SESSION_BUS_ADDRESS="unix:path=$TMPDIR/no-session-bus"
              ${westonSession nativeHostConfig nativeHomeConfig "wayland-native-polkit-smoke"}

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
              ${failOnQmlErrors}

              cleanup
              trap - EXIT
              touch "$out"
            '';

        quickshell-niri-state =
          pkgs.runCommand "quickshell-niri-state-test"
            {
              nativeBuildInputs = [ pkgs.nodejs ];
            }
            ''
              node --test ${../funforgiven/window-manager/quickshell}/tests/*.test.js
              touch "$out"
            '';

        quickshell-desktop-entries =
          pkgs.runCommandLocal "quickshell-desktop-entry-contract"
            {
              nativeBuildInputs = [ quickshell ];
            }
            ''
              set -euo pipefail

              export HOME="$TMPDIR/home"
              export XDG_CACHE_HOME="$TMPDIR/cache"
              export XDG_RUNTIME_DIR="$TMPDIR/runtime"
              export LC_ALL=C.UTF-8
              export XDG_DATA_DIRS="${homeConfig.home.path}/share:${hostConfig.system.path}/share"
              export QT_QPA_PLATFORM=offscreen
              export QS_DISABLE_FILE_WATCHER=1
              export QS_NO_RELOAD_POPUP=1
              mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR"
              chmod 0700 "$XDG_RUNTIME_DIR"

              qs -p ${desktopEntryProbe}
              touch "$out"
            '';

        quickshell-theme-contrast =
          pkgs.runCommandLocal "quickshell-theme-contrast"
            {
              nativeBuildInputs = [ pkgs.nodejs ];
            }
            ''
              set -euo pipefail
              node ${shellConfig}/tests/ThemeContrast.mjs ${shellConfig} ${materialPalette}
              touch "$out"
            '';
        funforgiven-shell-qml =
          pkgs.runCommandLocal "funforgiven-shell-qml-check"
            {
              nativeBuildInputs = [ pkgs.jq ];
            }
            ''
              set -euo pipefail

              shell_config=${shellConfig}
              export LC_ALL=C.UTF-8
              test -f "$shell_config/shell.qml"

              mapfile -d "" -t qml_files < <(
                find "$shell_config" \
                  -type d \( \
                    -name fixtures -o \
                    -name test -o \
                    -name testdata -o \
                    -name tests \
                  \) -prune -o \
                  -type f -name "*.qml" -print0 \
                  | sort -z
              )
              mapfile -d "" -t lint_files < <(
                find "$shell_config" \
                  -type d \( \
                    -name fixtures -o \
                    -name test -o \
                    -name testdata -o \
                    -name tests \
                  \) -prune -o \
                  -type f \( -name "*.js" -o -name "*.qml" \) -print0 \
                  | sort -z
              )

              if (( ''${#qml_files[@]} == 0 )); then
                echo "The generated funforgiven-shell config contains no runtime QML files." >&2
                exit 1
              fi

              while IFS= read -r -d "" qmldir; do
                directory="$(dirname "$qmldir")"
                for qml_file in "$directory"/*.qml; do
                  [[ -e "$qml_file" ]] || continue
                  qml_name="$(basename "$qml_file")"
                  [[ "$qml_name" == shell.qml ]] && continue

                  if ! grep -Eq \
                    "^[[:space:]]*(singleton[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]+[0-9]+\\.[0-9]+[[:space:]]+$qml_name[[:space:]]*$" \
                    "$qmldir"; then
                    echo "$qml_file is not exported by $qmldir." >&2
                    exit 1
                  fi
                done
              done < <(find "$shell_config" -type f -name qmldir -print0)

              ${pkgs.qt6.qtdeclarative}/bin/qmllint \
                --ignore-settings \
                --bare \
                --max-warnings 0 \
                ${pkgs.lib.escapeShellArgs qmlImportArgs} \
                "''${lint_files[@]}"

              mkdir -p "$out"
              ${pkgs.qt6.qtdeclarative}/libexec/qmlimportscanner \
                -qmlFiles "''${qml_files[@]}" \
                ${pkgs.lib.escapeShellArgs scannerImportArgs} \
                > "$out/imports.json"

              if ! jq -e '
                [
                  .[]
                  | select(.type == "module" and ((.path // "") == ""))
                ]
                | length == 0
              ' "$out/imports.json" >/dev/null; then
                echo "The generated funforgiven-shell config has unresolved QML imports:" >&2
                jq -r '
                  .[]
                  | select(.type == "module" and ((.path // "") == ""))
                  | "  - \(.name)"
                ' "$out/imports.json" >&2
                exit 1
              fi
            '';
        quickshell-qml-interactions =
          pkgs.runCommandLocal "quickshell-qml-interactions"
            {
              nativeBuildInputs = [ pkgs.qt6.qtdeclarative ];
            }
            ''
              set -euo pipefail
              export HOME="$TMPDIR/home"
              export XDG_RUNTIME_DIR="$TMPDIR/runtime"
              export QT_QPA_PLATFORM=offscreen
              export QT_QUICK_BACKEND=software
              mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
              chmod 0700 "$XDG_RUNTIME_DIR"

              ${pkgs.qt6.qtdeclarative}/bin/qmltestrunner \
                -input ${shellConfig}/tests \
                ${pkgs.lib.escapeShellArgs testImportArgs}
              touch "$out"
            '';
      };
    };
}
