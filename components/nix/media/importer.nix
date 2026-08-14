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
            local chat_id

            if [[ ! -r "$token_file" || ! -r "$chat_file" ]]; then
              return 0
            fi

            token="$(< "$token_file")"
            chat_id="$(< "$chat_file")"
            if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] ||
               [[ ! "$chat_id" =~ ^-?[0-9]+$ ]]; then
              unset token chat_id
              return 1
            fi

            {
              printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token"
            } | curl \
              --silent \
              --fail \
              --output /dev/null \
              --config - \
              --request POST \
              --data-urlencode "chat_id=$chat_id" \
              --data-urlencode "text=$message"
            unset token chat_id
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
      mediaImporterImage = pkgs.dockerTools.buildLayeredImage {
        name = "ghcr.io/funforgiven/media-importer";
        tag = "2.13.1";
        contents = [ mediaImporter ];
        extraCommands = ''
          mkdir -p state tmp
          chmod 1777 tmp
        '';
        config = {
          Entrypoint = [ "${mediaImporter}/bin/media-importer" ];
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

          printf '%s\n' \
            "ghcr.io/funforgiven/media-importer:$tag@$digest"
        '';
      };
    in
    {
      apps.promote-media-importer = {
        program = "${promoteMediaImporter}/bin/promote-media-importer";
        meta.description = "Publish the signed-revision media importer image to GHCR";
      };

      packages = {
        inherit mediaImporter;
        media-importer-image = mediaImporterImage;
        promote-media-importer = promoteMediaImporter;
      };
    };
}
