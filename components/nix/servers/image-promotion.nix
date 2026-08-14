{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      promoteServiceImages = pkgs.writeShellApplication {
        name = "promote-service-images";

        runtimeInputs = [
          pkgs.coreutils
          pkgs.findutils
          pkgs.gitMinimal
          pkgs.gnugrep
          pkgs.jq
          pkgs.nix
          pkgs.openstackclient
        ];

        text = ''
          set -euo pipefail

          repository_root="$(git rev-parse --show-toplevel)"
          cd "$repository_root"

          if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
            echo "Refusing to promote images from a dirty worktree." >&2
            exit 1
          fi

          revision="$(git rev-parse --verify HEAD)"
          git verify-commit "$revision" >/dev/null

          services_project_id="$(
            openstack project show services --format value --column id
          )"
          token_project_id="$(
            openstack token issue --format value --column project_id
          )"

          if [[ "$token_project_id" != "$services_project_id" ]]; then
            echo "The active OpenStack token must be scoped to the services project." >&2
            exit 1
          fi

          temporary_directory="$(mktemp --directory)"
          trap 'rm -rf "$temporary_directory"' EXIT

          for host in hermes home-assistant; do
            image_name="nixos-$host-''${revision:0:12}"

            nix build \
              --no-link \
              --print-out-paths \
              "$repository_root#$host-openstack-image" \
              > "$temporary_directory/$host-output-path"

            output_path="$(< "$temporary_directory/$host-output-path")"
            mapfile -t image_files < <(
              find "$output_path" -type f -name '*.qcow2' -print
            )

            if [[ "''${#image_files[@]}" -ne 1 ]]; then
              echo "Expected exactly one QCOW2 image for $host." >&2
              exit 1
            fi

            image_file="''${image_files[0]}"
            image_sha256="$(sha256sum "$image_file" | cut -d ' ' -f 1)"

            mapfile -t existing_ids < <(
              openstack image list \
                --name "$image_name" \
                --property "image_role=$host" \
                --property "image_source_revision=$revision" \
                --format value \
                --column ID
            )

            if [[ "''${#existing_ids[@]}" -gt 1 ]]; then
              echo "More than one immutable image matches $image_name." >&2
              exit 1
            fi

            if [[ "''${#existing_ids[@]}" -eq 1 ]]; then
              recorded_sha256="$(
                openstack image show "''${existing_ids[0]}" --format json |
                  jq --raw-output '.properties.image_source_sha256 // empty'
              )"

              if [[ "$recorded_sha256" != "$image_sha256" ]]; then
                echo "Existing image $image_name does not match the local build." >&2
                exit 1
              fi

              echo "$image_name already exists with the expected digest."
              continue
            fi

            openstack image create "$image_name" \
              --private \
              --protected \
              --container-format bare \
              --disk-format qcow2 \
              --file "$image_file" \
              --tag managed-by-nix \
              --property "hw_qemu_guest_agent=yes" \
              --property "image_role=$host" \
              --property "image_source_revision=$revision" \
              --property "image_source_sha256=$image_sha256" \
              --property "os_distro=nixos" \
              --property "os_type=linux" \
              --format value \
              --column id
          done
        '';
      };
    in
    {
      apps.promote-service-images = {
        program = "${promoteServiceImages}/bin/promote-service-images";
        meta.description = "Promote signed-revision NixOS service images into Glance";
      };

      packages = {
        hermes-openstack-image =
          inputs.self.nixosConfigurations.hermes.config.system.build.images.openstack;
        home-assistant-openstack-image =
          inputs.self.nixosConfigurations.home-assistant.config.system.build.images.openstack;
        nixos-anywhere = inputs.nixos-anywhere.packages.${pkgs.stdenv.hostPlatform.system}.nixos-anywhere;
        promote-service-images = promoteServiceImages;
      };
    };
}
