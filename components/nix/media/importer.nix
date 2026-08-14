_: {
  perSystem =
    { pkgs, ... }:
    let
      beetsPython = pkgs.python3Packages.beets.override {
        disableAllPlugins = true;
        doCheck = false;
        pluginOverrides = {
          chroma.enable = true;
          duplicates.enable = true;
          embedart.enable = true;
          fetchart.enable = true;
          fromfilename.enable = true;
          musicbrainz.enable = true;
        };
      };
      beets = pkgs.python3Packages.toPythonApplication beetsPython;
      beetsConfig = pkgs.writeText "beets-media-importer.yaml" ''
        directory: /media/library
        library: /state/library.db
        plugins:
          - chroma
          - duplicates
          - embedart
          - fetchart
          - fromfilename
          - musicbrainz

        import:
          copy: false
          duplicate_action: skip
          incremental: false
          move: true
          quiet: true
          quiet_fallback: skip
          resume: false
          timid: false
          write: true

        languages:
          - ja
          - en
        original_date: true
        per_disc_numbering: true

        paths:
          default: $albumartist/$album ($year)/$disc-$track $title
          singleton: Singles/$artist/$title
          comp: Compilations/$album ($year)/$disc-$track $title

        musicbrainz:
          extra_tags:
            - alias
            - barcode
            - catalognum
            - country
            - label
            - media
            - tracks
            - year
          genres: true
          https: true
          ratelimit: 1
          ratelimit_interval: 1.0

        chroma:
          auto: true

        fetchart:
          auto: true
          cautious: true
          enforce_ratio: 2%
          maxwidth: 1200
          sources:
            - filesystem
            - coverart: release
            - coverart: releasegroup
            - itunes

        embedart:
          auto: true
          compare_threshold: 0
          ifempty: false
          maxwidth: 1200
      '';
      mediaImporter = pkgs.writeShellApplication {
        name = "media-importer";
        runtimeInputs = [
          beets
          pkgs.coreutils
          pkgs.curl
          pkgs.findutils
          pkgs.jq
        ];
        text = ''
          set -euo pipefail
          shopt -s dotglob nullglob

          readonly inbox=/media/inbox
          readonly processing=/media/processing
          readonly quarantine=/media/quarantine
          readonly token_file=''${TELEGRAM_BOT_TOKEN_FILE:-/run/secrets/telegram/bot-token}
          readonly chat_file=''${TELEGRAM_CHAT_ID_FILE:-/run/secrets/telegram/chat-id}

          notify() {
            local message="$1"
            local token

            if [[ ! -r "$token_file" || ! -r "$chat_file" ]]; then
              return 0
            fi

            token="$(< "$token_file")"
            if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] ||
               ! grep -Eq '^-?[0-9]+$' "$chat_file"; then
              unset token
              return 1
            fi

            jq --null-input --compact-output \
              --rawfile chat_id "$chat_file" \
              --arg text "$message" \
              '{chat_id: ($chat_id | rtrimstr("\n")), text: $text}' | \
            curl \
              --silent \
              --show-error \
              --fail \
              --output /dev/null \
              --config <(
              printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token"
              ) \
              --request POST \
              --header 'Content-Type: application/json' \
              --data-binary @-
            unset token
          }

          mkdir -p "$inbox" "$processing" "$quarantine" /state

          while IFS= read -r -d "" candidate; do
            timestamp="$(date --utc +%Y%m%dT%H%M%SZ)"
            name="$(basename -- "$candidate")"
            display_name="''${name//$'\n'/ }"

            if [[ ! -d "$candidate" ]]; then
              destination="$quarantine/$timestamp-$name"
              mv -- "$candidate" "$destination"
              notify "Music import needs review: $display_name was uploaded outside an album directory."
              continue
            fi

            working="$processing/$timestamp-$name"
            if [[ -e "$working" ]]; then
              notify "Music import collision: $display_name remains in the inbox."
              continue
            fi
            mv -- "$candidate" "$working"

            import_exit=0
            beet -c ${beetsConfig} import --quiet --move "$working" ||
              import_exit=$?

            remaining="$(find "$working" -mindepth 1 -print -quit 2>/dev/null || true)"
            if [[ "$import_exit" -eq 0 && -z "$remaining" ]]; then
              if [[ -d "$working" ]]; then
                rmdir -- "$working"
              fi
              notify "Music imported into Navidrome: $display_name"
              continue
            fi

            destination="$quarantine/$timestamp-$name"
            mv -- "$working" "$destination"
            notify "Music import needs metadata review: $display_name was moved to quarantine."
          done < <(find "$inbox" -mindepth 1 -maxdepth 1 -print0)
        '';
      };
      releaseWatcher = pkgs.writeShellApplication {
        name = "music-release-watcher";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.curl
          pkgs.gnugrep
          pkgs.jq
        ];
        text = ''
          set -euo pipefail

          readonly watchlist=/config/artists.tsv
          readonly state_directory=/state/release-watcher
          readonly seen_file="$state_directory/seen-release-groups"
          readonly karakeep_key_file=/run/secrets/release-watcher/karakeep-api-key
          readonly telegram_token_file=/run/secrets/release-watcher/telegram-bot-token
          readonly telegram_chat_file=/run/secrets/release-watcher/telegram-chat-id
          readonly user_agent='fahrican-release-watcher/1.0 (+https://github.com/funforgiven/infra)'

          require_file() {
            [[ -r "$1" && -s "$1" ]]
          }

          require_file "$watchlist"
          require_file "$karakeep_key_file"
          require_file "$telegram_token_file"
          require_file "$telegram_chat_file"

          IFS= read -r karakeep_key < "$karakeep_key_file"
          IFS= read -r telegram_token < "$telegram_token_file"
          [[ "$karakeep_key" =~ ^[A-Za-z0-9._-]+$ ]]
          [[ "$telegram_token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]
          grep -Eq '^-?[0-9]+$' "$telegram_chat_file"

          mkdir -p "$state_directory"
          touch "$seen_file"

          curl \
            --silent \
            --show-error \
            --fail \
            --retry 3 \
            --retry-all-errors \
            --max-time 60 \
            --user-agent "$user_agent" \
            --get 'https://api.listenbrainz.org/1/explore/fresh-releases/' \
            --data-urlencode "release_date=$(date --utc +%F)" \
            --data-urlencode 'days=90' \
            --data-urlencode 'sort=release_date' \
            --data-urlencode 'past=true' \
            --data-urlencode 'future=true' \
            --output /tmp/fresh-releases.json

          jq -e '.payload.releases | type == "array"' \
            /tmp/fresh-releases.json >/dev/null

          while IFS= read -r release; do
            matched_artist=""
            artist_tag=""
            while IFS='|' read -r artist_mbid artist_name configured_tag; do
              [[ "$artist_mbid" =~ ^[0-9a-f-]{36}$ ]]
              [[ -n "$artist_name" ]]
              [[ "$configured_tag" =~ ^artist/[a-z0-9-]+$ ]]
              if jq -e --arg mbid "$artist_mbid" \
                '(.artist_mbids // []) | index($mbid) != null' \
                <<< "$release" >/dev/null; then
                matched_artist="$artist_name"
                artist_tag="$configured_tag"
                break
              fi
            done < "$watchlist"

            if [[ -z "$matched_artist" ]]; then
              continue
            fi

            release_group_mbid="$(jq -er '.release_group_mbid' <<< "$release")"
            release_name="$(jq -er '.release_name' <<< "$release")"
            release_date="$(jq -er '.release_date // "date unknown"' <<< "$release")"
            [[ "$release_group_mbid" =~ ^[0-9a-f-]{36}$ ]]
            if grep -Fxq "$release_group_mbid" "$seen_file"; then
              continue
            fi

            musicbrainz_url="https://musicbrainz.org/release-group/$release_group_mbid"
            query="$matched_artist $release_name"
            encoded_query="$(jq -rn --arg value "$query" '$value | @uri')"
            bandcamp_url="https://bandcamp.com/search?q=$encoded_query"
            ototoy_url="https://search.fahrican.com/search?q=site%3Aototoy.jp%20$encoded_query"
            title="Purchase review: $matched_artist — $release_name"
            note="Release date: $release_date\n\nBandcamp: $bandcamp_url\nOTOTOY search: $ototoy_url\n\nCheckout is always manual. Upload purchased files through SFTPGo for tagging and import."

            bookmark_payload="$(
              jq -n \
                --arg title "$title" \
                --arg url "$musicbrainz_url" \
                --arg note "$note" \
                '{type:"link", url:$url, title:$title, note:$note, favourited:true, source:"api", crawlPriority:"low"}'
            )"
            bookmark_response="$(
              {
                printf 'url = "https://keep.fahrican.com/api/v1/bookmarks"\n'
                printf 'header = "Authorization: Bearer %s"\n' "$karakeep_key"
              } | curl \
                --silent \
                --show-error \
                --fail \
                --max-time 30 \
                --config - \
                --header 'Content-Type: application/json' \
                --request POST \
                --data "$bookmark_payload"
            )"
            bookmark_id="$(jq -er '.id' <<< "$bookmark_response")"
            [[ "$bookmark_id" =~ ^[A-Za-z0-9_-]+$ ]]

            tag_payload="$(
              jq -n \
                --arg artist_tag "$artist_tag" \
                '{tags:[
                  {tagName:"music/wanted", attachedBy:"human"},
                  {tagName:"release/new", attachedBy:"human"},
                  {tagName:$artist_tag, attachedBy:"human"}
                ]}'
            )"
            {
              printf 'url = "https://keep.fahrican.com/api/v1/bookmarks/%s/tags"\n' "$bookmark_id"
              printf 'header = "Authorization: Bearer %s"\n' "$karakeep_key"
            } | curl \
              --silent \
              --show-error \
              --fail \
              --output /dev/null \
              --max-time 30 \
              --config - \
              --header 'Content-Type: application/json' \
              --request POST \
              --data "$tag_payload"

            message="$title ($release_date)\n\nReview in Karakeep: $musicbrainz_url\nBandcamp: $bandcamp_url\nOTOTOY: $ototoy_url"
            jq --null-input --compact-output \
              --rawfile chat_id "$telegram_chat_file" \
              --arg text "$message" \
              '{chat_id: ($chat_id | rtrimstr("\n")), text: $text}' | \
            curl \
              --silent \
              --show-error \
              --fail \
              --output /dev/null \
              --max-time 30 \
              --config <(
              printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$telegram_token"
              ) \
              --request POST \
              --header 'Content-Type: application/json' \
              --data-binary @-

            printf '%s\n' "$release_group_mbid" >> "$seen_file"
            sort -u -o "$seen_file" "$seen_file"
          done < <(jq -c '.payload.releases[]' /tmp/fresh-releases.json)

          unset karakeep_key telegram_token
        '';
      };
      mediaJobs = pkgs.writeShellApplication {
        name = "media-jobs";
        runtimeInputs = [
          mediaImporter
          releaseWatcher
        ];
        text = ''
          set -euo pipefail

          case "''${MEDIA_JOB:-importer}" in
            importer) exec media-importer "$@" ;;
            release-watcher) exec music-release-watcher "$@" ;;
            *) echo "Unknown media job." >&2; exit 64 ;;
          esac
        '';
      };
      mediaImporterImage = pkgs.dockerTools.buildLayeredImage {
        name = "ghcr.io/funforgiven/media-importer";
        tag = "2.13.1";
        contents = [ mediaJobs ];
        extraCommands = ''
          mkdir -p state tmp
          chmod 1777 tmp
        '';
        config = {
          Entrypoint = [ "${mediaJobs}/bin/media-jobs" ];
          Env = [
            "HOME=/state"
            "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "TMPDIR=/tmp"
          ];
          User = "1000:1000";
          WorkingDir = "/state";
        };
      };
      promoteMediaImporter = pkgs.writeShellApplication {
        name = "promote-media-importer";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.gnugrep
          pkgs.gnused
          pkgs.nix
          pkgs.skopeo
        ];
        text = ''
          set -euo pipefail

          repository_root="$(git rev-parse --show-toplevel)"
          cd "$repository_root"

          if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
            echo "Refusing to promote an image from a dirty worktree." >&2
            exit 1
          fi

          revision="$(git rev-parse --verify HEAD)"
          git verify-commit "$revision" >/dev/null

          : "''${REGISTRY_AUTH_FILE:?Set REGISTRY_AUTH_FILE to a root-only containers auth file}"
          if [[ ! -r "$REGISTRY_AUTH_FILE" ]]; then
            echo "REGISTRY_AUTH_FILE is not readable." >&2
            exit 1
          fi

          auth_mode="$(stat --format=%a "$REGISTRY_AUTH_FILE")"
          if [[ "$auth_mode" != 400 && "$auth_mode" != 600 ]]; then
            echo "REGISTRY_AUTH_FILE must have mode 0400 or 0600." >&2
            exit 1
          fi

          archive="$(
            nix build \
              --no-link \
              --print-out-paths \
              "$repository_root#media-importer-image"
          )"
          tag="2.13.1-''${revision:0:12}"
          destination="docker://ghcr.io/funforgiven/media-importer:$tag"

          skopeo copy \
            --authfile "$REGISTRY_AUTH_FILE" \
            "docker-archive:$archive" \
            "$destination"

          digest="$(
            skopeo inspect \
              --authfile "$REGISTRY_AUTH_FILE" \
              --format '{{.Digest}}' \
              "$destination"
          )"
          if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
            echo "Registry returned an invalid digest." >&2
            exit 1
          fi

          promoted_image="ghcr.io/funforgiven/media-importer:$tag@$digest"
          manifests=(
            deployments/homelab/cloud/services/40-media/importer.yaml
            deployments/homelab/cloud/services/40-media/release-watcher.yaml
            deployments/homelab/cloud/versions.yaml
          )
          for manifest in "''${manifests[@]}"; do
            if [[ "$(grep -Ec 'ghcr\.io/funforgiven/media-importer:[^@[:space:]]+@sha256:[0-9a-f]{64}' "$manifest")" -ne 1 ]]; then
              echo "$manifest must contain exactly one pinned media image." >&2
              exit 1
            fi
            sed -Ei \
              "s#ghcr\.io/funforgiven/media-importer:[^@[:space:]]+@sha256:[0-9a-f]{64}#$promoted_image#" \
              "$manifest"
          done

          printf '%s\n' "$promoted_image"
          printf '%s\n' \
            'Updated both CronJobs and versions.yaml; review and create a signed promotion commit.'
        '';
      };
    in
    {
      apps.promote-media-importer = {
        program = "${promoteMediaImporter}/bin/promote-media-importer";
        meta.description = "Publish the signed-revision media importer image to GHCR";
      };

      packages = {
        inherit mediaImporter releaseWatcher;
        media-importer-image = mediaImporterImage;
        promote-media-importer = promoteMediaImporter;
      };
    };
}
