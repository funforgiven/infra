{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      promoteServiceImages = pkgs.writeShellApplication {
        name = "promote-service-images";

        runtimeInputs = [
          pkgs.coreutils
          pkgs.curl
          pkgs.findutils
          pkgs.gitMinimal
          pkgs.jq
          pkgs.nix
          pkgs.openstackclient
          pkgs.sops
          pkgs.xz
          pkgs.yq-go
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

          if [[ -z "''${OS_AUTH_URL:-}" ]]; then
            openstack_values=deployments/homelab/cloud/undercloud/71-magnum/secrets.sops.yaml
            export OS_AUTH_TYPE=password
            export OS_AUTH_URL=https://identity.cloud.fahrican.com/v3
            export OS_IDENTITY_API_VERSION=3
            export OS_INTERFACE=public
            OS_PASSWORD="$(
              sops decrypt \
                --extract '["stringData"]["values.yaml"]' \
                "$openstack_values" |
                yq eval --unwrapScalar '.endpoints.identity.auth.admin.password' -
            )"
            export OS_PASSWORD
            export OS_PROJECT_DOMAIN_NAME=Default
            export OS_PROJECT_NAME=services
            export OS_REGION_NAME=RegionOne
            export OS_USER_DOMAIN_NAME=Default
            export OS_USERNAME=admin
            if [[ -z "$OS_PASSWORD" || "$OS_PASSWORD" == null ]]; then
              echo "The encrypted OpenStack administrator profile is incomplete." >&2
              exit 1
            fi
          fi

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

          host=hermes
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
          else
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
          fi

          haos_version=18.2
          haos_name="haos-$haos_version"
          haos_archive_sha256=254e53f354df0739e3afc09be5431a07df53f0df6b703885404f665c454f254e
          haos_url="https://github.com/home-assistant/operating-system/releases/download/$haos_version/haos_ova-$haos_version.qcow2.xz"

          mapfile -t haos_existing_ids < <(
            openstack image list \
              --name "$haos_name" \
              --property image_role=home-assistant-os \
              --property "haos_version=$haos_version" \
              --format value \
              --column ID
          )

          if [[ "''${#haos_existing_ids[@]}" -gt 1 ]]; then
            echo "More than one immutable image matches $haos_name." >&2
            exit 1
          fi

          if [[ "''${#haos_existing_ids[@]}" -eq 1 ]]; then
            recorded_archive_sha256="$(
              openstack image show "''${haos_existing_ids[0]}" --format json |
                jq --raw-output '.properties.image_source_archive_sha256 // empty'
            )"
            if [[ "$recorded_archive_sha256" != "$haos_archive_sha256" ]]; then
              echo "Existing image $haos_name has an unexpected source digest." >&2
              exit 1
            fi
            echo "$haos_name already exists from the pinned official asset."
          else
            haos_archive="$temporary_directory/$haos_name.qcow2.xz"
            haos_image="$temporary_directory/$haos_name.qcow2"
            curl --fail --location --retry 5 --output "$haos_archive" "$haos_url"
            printf '%s  %s\n' "$haos_archive_sha256" "$haos_archive" |
              sha256sum --check --strict
            xz --decompress --stdout "$haos_archive" > "$haos_image"
            haos_image_sha256="$(sha256sum "$haos_image" | cut -d ' ' -f 1)"

            openstack image create "$haos_name" \
              --private \
              --protected \
              --container-format bare \
              --disk-format qcow2 \
              --file "$haos_image" \
              --tag managed-by-nix \
              --property hw_firmware_type=uefi \
              --property hw_machine_type=q35 \
              --property image_role=home-assistant-os \
              --property "haos_version=$haos_version" \
              --property "image_source_archive_sha256=$haos_archive_sha256" \
              --property "image_source_sha256=$haos_image_sha256" \
              --property "image_source_url=$haos_url" \
              --property os_distro=home-assistant \
              --property os_type=linux \
              --format value \
              --column id
          fi

          printf '%s\n' \
            "Promoted Hermes candidate $image_name for $revision and HAOS $haos_version." \
            'Active boot-volume revisions were intentionally left unchanged.'
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
        nixos-anywhere = inputs.nixos-anywhere.packages.${pkgs.stdenv.hostPlatform.system}.nixos-anywhere;
        promote-service-images = promoteServiceImages;
      };
    };
}
