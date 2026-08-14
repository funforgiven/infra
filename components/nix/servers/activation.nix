_: {
  perSystem =
    { pkgs, ... }:
    let
      enrollServicesCredential = pkgs.writeShellApplication {
        name = "enroll-services-credential";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.jq
          pkgs.sops
        ];
        text = ''
          set -euo pipefail
          umask 077

          if [[ "$#" -ne 1 ]]; then
            echo "Usage: enroll-services-credential KEY" >&2
            exit 64
          fi

          readonly key="$1"
          case "$key" in
            CLOUDFLARE_R2_API_TOKEN|HCLOUD_TOKEN|INFRA_TELEGRAM_BOT_TOKEN|INFRA_TELEGRAM_CHAT_ID|MEDIA_TELEGRAM_BOT_TOKEN|MEDIA_TELEGRAM_CHAT_ID|ND_LASTFM_APIKEY|ND_LASTFM_SECRET|ND_PASSWORDENCRYPTIONKEY|R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|RELEASE_WATCHER_KARAKEEP_API_KEY|RESEND_ADMIN_API_KEY|SFTPGO_ADMIN_PASSWORD|SFTPGO_USER_PASSWORD|MAIL_MANAGEMENT_CIDRS_JSON) ;;
            *)
              echo "Unknown services credential key: $key" >&2
              exit 64
              ;;
          esac

          repository_root="$(git rev-parse --show-toplevel)"
          secret_file="$repository_root/deployments/homelab/cloud/undercloud/81-services-foundation/runtime.sops.yaml"
          [[ -f "$secret_file" ]]

          printf 'Enter %s (input hidden): ' "$key" >&2
          IFS= read -r -s value
          printf '\nRepeat %s: ' "$key" >&2
          IFS= read -r -s confirmation
          printf '\n' >&2
          if [[ -z "$value" || "$value" != "$confirmation" ]]; then
            unset value confirmation
            echo 'Values were empty or did not match.' >&2
            exit 1
          fi

          encoded="$(printf '%s' "$value" | base64 --wrap=0)"
          unset value confirmation
          printf '%s' "$encoded" | jq --raw-input . | \
            sops set --value-stdin "$secret_file" "[\"data\"][\"$key\"]"
          unset encoded

          printf '%s\n' \
            "$key was added as SOPS ciphertext. No plaintext value was written to Git or passed as an argument."
        '';
      };
      servicesActivationPreflight = pkgs.writeShellApplication {
        name = "services-activation-preflight";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.ripgrep
          pkgs.sops
        ];
        text = ''
          set -euo pipefail

          repository_root="$(git rev-parse --show-toplevel)"
          cd "$repository_root"
          if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
            echo 'Activation requires a clean worktree.' >&2
            exit 1
          fi
          git verify-commit HEAD >/dev/null

          secret_file=deployments/homelab/cloud/undercloud/81-services-foundation/runtime.sops.yaml
          sops filestatus "$secret_file" | rg --quiet '"encrypted":true'
          required_keys=(
            CLOUDFLARE_R2_API_TOKEN
            HCLOUD_TOKEN
            INFRA_TELEGRAM_BOT_TOKEN
            INFRA_TELEGRAM_CHAT_ID
            MAIL_MANAGEMENT_CIDRS_JSON
            MEDIA_TELEGRAM_BOT_TOKEN
            MEDIA_TELEGRAM_CHAT_ID
            ND_LASTFM_APIKEY
            ND_LASTFM_SECRET
            ND_PASSWORDENCRYPTIONKEY
            R2_ACCESS_KEY_ID
            R2_SECRET_ACCESS_KEY
            RELEASE_WATCHER_KARAKEEP_API_KEY
            RESEND_ADMIN_API_KEY
            SFTPGO_ADMIN_PASSWORD
            SFTPGO_USER_PASSWORD
          )
          for key in "''${required_keys[@]}"; do
            rg --quiet "^[[:space:]]+$key: ENC\\[" "$secret_file" || {
              echo "Missing encrypted runtime key: $key" >&2
              exit 1
            }
          done

          if rg --quiet 'sha256:0{64}' \
            deployments/homelab/cloud/services/40-media \
            deployments/homelab/cloud/versions.yaml; then
            echo 'The media image has not passed signed-revision promotion.' >&2
            exit 1
          fi
          if rg --quiet 'value: "0{40}"' \
            deployments/homelab/cloud/undercloud/83-services-hosts/tofu.yaml; then
            echo 'The service-host images have not passed signed-revision promotion.' >&2
            exit 1
          fi

          printf '%s\n' \
            'Repository activation preflight passed.' \
            'Runtime values will be validated again by the in-cluster reconciler.'
        '';
      };
      advanceServicesActivation = pkgs.writeShellApplication {
        name = "advance-services-activation";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.python3
        ];
        text = ''
          set -euo pipefail

          if [[ "$#" -ne 1 ]]; then
            echo 'Usage: advance-services-activation STAGE' >&2
            echo 'Stages: foundation cluster hosts mail dns observability backup-controller backup-policy knowledge media home-automation synthetic-monitoring' >&2
            exit 64
          fi

          repository_root="$(git rev-parse --show-toplevel)"
          cd "$repository_root"
          if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
            echo 'Activation advancement requires a clean worktree.' >&2
            exit 1
          fi
          git verify-commit HEAD >/dev/null

          readonly undercloud_waves=deployments/homelab/cloud/undercloud/20-gitops/waves.yaml
          readonly services_waves=deployments/homelab/cloud/services/waves.yaml
          targets=()
          case "$1" in
            foundation)
              targets+=("$undercloud_waves|wave81-services-foundation")
              ;;
            cluster)
              targets+=("$undercloud_waves|wave82-services-cluster")
              ;;
            hosts)
              targets+=("$undercloud_waves|wave83-services-hosts")
              targets+=("deployments/homelab/cloud/undercloud/83-services-hosts/tofu.yaml|services-hosts")
              ;;
            mail)
              targets+=("$undercloud_waves|wave84-mail-edge")
              targets+=("deployments/homelab/cloud/undercloud/84-mail-edge/tofu.yaml|mail-edge")
              ;;
            dns)
              targets+=("$undercloud_waves|wave85-service-dns")
              targets+=("deployments/homelab/cloud/undercloud/85-service-dns/tofu.yaml|service-dns")
              ;;
            observability)
              targets+=("$services_waves|services-observability")
              ;;
            backup-controller)
              targets+=("$services_waves|services-backup-controller")
              ;;
            backup-policy)
              targets+=("$services_waves|services-backup-policy")
              ;;
            knowledge)
              targets+=("$services_waves|services-knowledge")
              ;;
            media)
              targets+=("$services_waves|services-media")
              ;;
            home-automation)
              targets+=("$services_waves|services-home-automation")
              ;;
            synthetic-monitoring)
              targets+=("$services_waves|services-synthetic-monitoring")
              ;;
            *)
              echo "Unknown activation stage: $1" >&2
              exit 64
              ;;
          esac

          for target in "''${targets[@]}"; do
            file="''${target%%|*}"
            resource="''${target#*|}"
            python3 - "$file" "$resource" <<'PY'
          import pathlib
          import sys

          path = pathlib.Path(sys.argv[1])
          resource = sys.argv[2]
          text = path.read_text(encoding="utf-8")
          documents = text.split("\n---\n")
          matches = [
              index
              for index, document in enumerate(documents)
              if f"\n  name: {resource}\n" in "\n" + document
          ]
          if len(matches) != 1:
              raise SystemExit(
                  f"{path}: expected one document named {resource}, found {len(matches)}"
              )
          index = matches[0]
          suspended = "\n  suspend: true\n"
          active = "\n  suspend: false\n"
          if suspended not in "\n" + documents[index]:
              if active in "\n" + documents[index]:
                  raise SystemExit(f"{path}: {resource} is already active")
              raise SystemExit(f"{path}: {resource} has no explicit suspension gate")
          documents[index] = documents[index].replace(suspended, active, 1)
          path.write_text("\n---\n".join(documents), encoding="utf-8")
          PY
          done

          git diff --check
          printf '%s\n' \
            "Activation stage '$1' is now enabled in the declarative manifests." \
            'Review the diff, run the repository checks, create a signed Conventional Commit, and push it directly to main.'
        '';
      };
      enrollServiceHostSecrets = pkgs.writeShellApplication {
        name = "enroll-service-host-secrets";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.openssh
        ];
        text = ''
          set -euo pipefail
          umask 077

          if [[ "$#" -lt 2 || "$#" -gt 3 ]]; then
            echo 'Usage: enroll-service-host-secrets SSH_TARGET PROFILE [R2_ENDPOINT]' >&2
            echo 'Profiles: monitoring hermes-runtime mail-runtime hermes-backup home-assistant-backup mail-edge-backup' >&2
            exit 64
          fi

          readonly ssh_target="$1"
          readonly profile="$2"
          bot_token=
          chat_id=
          allowed_users=
          home_channel=
          karakeep_key=
          admin_secret=
          resend_key=
          restic_password=
          access_key_id=
          secret_access_key=
          if [[ "$ssh_target" == -* || ! "$ssh_target" =~ ^[A-Za-z0-9_.@:-]+$ ]]; then
            echo 'SSH_TARGET contains unsupported characters.' >&2
            exit 64
          fi

          prompt_value() {
            local variable="$1"
            local label="$2"
            local pattern="$3"
            local minimum="$4"
            local maximum="$5"
            local value
            local confirmation

            printf 'Enter %s (input hidden): ' "$label" >&2
            IFS= read -r -s value
            printf '\nRepeat %s: ' "$label" >&2
            IFS= read -r -s confirmation
            printf '\n' >&2
            if [[ "$value" != "$confirmation" ]] ||
               [[ "''${#value}" -lt "$minimum" ]] ||
               [[ "''${#value}" -gt "$maximum" ]] ||
               [[ ! "$value" =~ $pattern ]]; then
              unset value confirmation
              echo "$label was empty, mismatched, or invalid." >&2
              exit 1
            fi
            printf -v "$variable" '%s' "$value"
            unset value confirmation
          }

          prepare_directory() {
            # The client-side value is selected only from the constant paths
            # below and is intentionally expanded before the SSH boundary.
            # shellcheck disable=SC2029
            ssh "$ssh_target" \
              "sudo install -d -o root -g root -m 0700 '$1'"
          }

          install_stream() {
            local destination="$1"
            # The destination is a constant allow-listed path; credential
            # bytes travel exclusively through this function's standard input.
            # shellcheck disable=SC2029
            ssh "$ssh_target" \
              "sudo install -o root -g root -m 0400 /dev/stdin '$destination'"
          }

          case "$profile" in
            monitoring)
              [[ "$#" -eq 2 ]]
              prompt_value bot_token 'infrastructure Telegram bot token' \
                '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
              prompt_value chat_id 'infrastructure Telegram chat ID' \
                '^-?[0-9]+$' 1 32
              prepare_directory /var/lib/monitoring-bootstrap
              printf '%s' "$bot_token" | \
                install_stream /var/lib/monitoring-bootstrap/bot-token
              printf '%s' "$chat_id" | \
                install_stream /var/lib/monitoring-bootstrap/chat-id
              unset bot_token chat_id
              ;;
            hermes-runtime)
              [[ "$#" -eq 2 ]]
              prompt_value bot_token 'Hermes Telegram bot token' \
                '^[0-9]+:[A-Za-z0-9_-]+$' 32 256
              prompt_value allowed_users 'comma-separated Telegram user allowlist' \
                '^[0-9]+(,[0-9]+)*$' 1 512
              prompt_value home_channel 'Hermes Telegram home channel ID' \
                '^-?[0-9]+$' 1 32
              prompt_value karakeep_key 'Hermes Karakeep API key' \
                '^[A-Za-z0-9._-]+$' 32 512
              prepare_directory /var/lib/hermes-bootstrap
              {
                printf 'TELEGRAM_BOT_TOKEN=%s\n' "$bot_token"
                printf 'TELEGRAM_ALLOWED_USERS=%s\n' "$allowed_users"
                printf 'TELEGRAM_HOME_CHANNEL=%s\n' "$home_channel"
                printf 'KARAKEEP_API_KEY=%s\n' "$karakeep_key"
              } | install_stream /var/lib/hermes-bootstrap/runtime.env
              unset bot_token allowed_users home_channel karakeep_key
              ;;
            mail-runtime)
              [[ "$#" -eq 2 ]]
              prompt_value admin_secret 'Stalwart fallback administrator secret' \
                '^.+$' 32 1024
              prompt_value resend_key 'Resend domain sending key' \
                '^re_[A-Za-z0-9_-]+$' 23 512
              prepare_directory /var/lib/stalwart-bootstrap
              printf '%s' "$admin_secret" | \
                install_stream /var/lib/stalwart-bootstrap/admin-secret
              printf '%s' "$resend_key" | \
                install_stream /var/lib/stalwart-bootstrap/resend-api-key
              unset admin_secret resend_key
              ;;
            hermes-backup|home-assistant-backup|mail-edge-backup)
              [[ "$#" -eq 3 ]]
              readonly endpoint="$3"
              if [[ ! "$endpoint" =~ ^https://[0-9a-f]{32}\.r2\.cloudflarestorage\.com$ ]]; then
                echo 'R2_ENDPOINT must be the exact OpenTofu account endpoint.' >&2
                exit 64
              fi
              case "$profile" in
                hermes-backup) bucket=fahrican-hermes-backup ;;
                home-assistant-backup) bucket=fahrican-home-assistant-backup ;;
                mail-edge-backup) bucket=fahrican-mail-edge-backup ;;
              esac
              prompt_value restic_password 'Restic repository password' \
                '^.+$' 32 1024
              prompt_value access_key_id 'bucket-scoped R2 access key ID' \
                '^[A-Za-z0-9_-]+$' 16 256
              prompt_value secret_access_key 'bucket-scoped R2 secret access key' \
                '^[A-Za-z0-9/+_-]+={0,2}$' 32 512
              prepare_directory /var/lib/backup-bootstrap
              printf 's3:%s/%s' "$endpoint" "$bucket" | \
                install_stream /var/lib/backup-bootstrap/repository
              printf '%s' "$restic_password" | \
                install_stream /var/lib/backup-bootstrap/password
              {
                printf 'AWS_ACCESS_KEY_ID=%s\n' "$access_key_id"
                printf 'AWS_SECRET_ACCESS_KEY=%s\n' "$secret_access_key"
                printf 'AWS_DEFAULT_REGION=auto\n'
              } | install_stream /var/lib/backup-bootstrap/environment
              unset restic_password access_key_id secret_access_key
              ;;
            *)
              echo "Unknown host enrollment profile: $profile" >&2
              exit 64
              ;;
          esac

          printf '%s\n' \
            "Enrolled '$profile' on '$ssh_target' through SSH standard input." \
            'No credential was placed in an argument, local file, or repository.'
        '';
      };
    in
    {
      apps.advance-services-activation = {
        program = "${advanceServicesActivation}/bin/advance-services-activation";
        meta.description = "Enable one service activation stage in Git-managed Flux manifests";
      };

      apps.enroll-services-credential = {
        program = "${enrollServicesCredential}/bin/enroll-services-credential";
        meta.description = "Enroll one credential into the services SOPS bootstrap without argv exposure";
      };

      apps.enroll-service-host-secrets = {
        program = "${enrollServiceHostSecrets}/bin/enroll-service-host-secrets";
        meta.description = "Stream a validated root-only credential profile to a service host";
      };

      apps.services-activation-preflight = {
        program = "${servicesActivationPreflight}/bin/services-activation-preflight";
        meta.description = "Verify credential ciphertext, promotions, and signed clean state before activation";
      };

      packages = {
        advance-services-activation = advanceServicesActivation;
        enroll-service-host-secrets = enrollServiceHostSecrets;
        enroll-services-credential = enrollServicesCredential;
        services-activation-preflight = servicesActivationPreflight;
      };
    };
}
