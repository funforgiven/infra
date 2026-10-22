_: {
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);
      # Runs OpenTofu in one provider root with the state passphrase held only
      # in this process environment; state and plans stay encrypted on disk.
      tofu = pkgs.writeShellApplication {
        name = "homelab-tofu";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.gzip
          pkgs.jq
          pkgs.opentofu
          pkgs.sops
        ];
        text = ''
          roots=(aws-iam backblaze dns identity mail-aws netbird)
          root="''${1:-}"
          if [[ ! " ''${roots[*]} " =~ \ $root\  ]]; then
            echo "Usage: nix run .#tofu -- {$(IFS='|'; echo "''${roots[*]}")} TOFU_ARGUMENTS..." >&2
            exit 64
          fi
          shift
          top="$(git rev-parse --show-toplevel)"
          TF_VAR_state_passphrase="$(
            sops decrypt --extract '["passphrase"]' "$top/secrets/opentofu-state.sops.yaml"
          )"
          export TF_VAR_state_passphrase
          directory="$top/components/homelab/providers/$root"

          # One-time import of the pre-encryption state snapshot. Plaintext
          # exists only in this pipeline. Delete this branch, and
          # secrets/current-provider-state.sops.yaml, once every root migrated.
          if [[ "''${1:-}" == migrate-legacy-state ]]; then
            declare -A legacy=(
              [dns]=tfstate-default-service-dns
              [identity]=tfstate-default-zitadel
              [mail-aws]=tfstate-default-mail-aws
              [netbird]=tfstate-default-netbird-policy
            )
            name="''${legacy[$root]:?no legacy state for $root}"
            if [[ -e "$directory/terraform.tfstate" ]]; then
              echo "$root already has encrypted state." >&2
              exit 1
            fi
            tofu -chdir="$directory" init -input=false
            # `state push` reads the plaintext stream and writes it encrypted.
            sops decrypt --output-type json "$top/secrets/current-provider-state.sops.yaml" |
              jq --exit-status --raw-output --arg name "$name" \
                '[.objects[] | select(.metadata.name == $name)] | if length == 1 then .[0].data.tfstate else error("ambiguous") end' |
              base64 --decode | gzip --decompress --force --stdout |
              tofu -chdir="$directory" state push -
            tofu -chdir="$directory" state list >/dev/null
            echo "Migrated $root state into $directory/terraform.tfstate (encrypted)."
            exit 0
          fi

          exec tofu -chdir="$directory" "$@"
        '';
      };
      identityCredentials = pkgs.writeShellApplication {
        name = "identity-credentials";
        runtimeInputs = [ pkgs.sops ];
        text = ''
          export PYTHONPATH=${../../homelab/operations}
          exec ${python}/bin/python ${../../homelab/operations/identity_credentials.py} "$@"
        '';
      };
    in
    {
      apps.tofu = {
        program = "${tofu}/bin/homelab-tofu";
        meta.description = "Run OpenTofu in a provider root with encrypted state";
      };
      apps.identity-credentials = {
        program = "${identityCredentials}/bin/identity-credentials";
        meta.description = "Copy ZITADEL client credentials from identity outputs into consumer SOPS files";
      };
    };
}
