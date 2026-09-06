_: {
  perSystem =
    {
      pkgs,
      lib,
      system,
      ...
    }:
    {
      packages = lib.optionalAttrs (system == "x86_64-linux") {
        # Preserve the deployed OpenStack image and add the pinned TPM tools.
        # The tss identity matches the Nova image so migration state ownership
        # is consistent across the two containers.
        libvirt-tpm-image =
          let
            base = pkgs.dockerTools.pullImage {
              imageName = "quay.io/airshipit/libvirt";
              imageDigest = "sha256:0eab160c828f6f8689e90c4727df92c4fea81d705f6279bd00a878604af48ff7";
              hash = "sha256-SXC9kyi0QPytR2Ygdm7PRekjoVfG6X1q4ZXoVzKkRn8=";
              finalImageTag = "2026.1-ubuntu_noble";
            };
            root = pkgs.runCommand "libvirt-tpm-root" { nativeBuildInputs = [ pkgs.python3 ]; } ''
              mkdir -p "$out/etc" "$out/usr/bin" "$out/var/lib/swtpm-localca"
              python3 - ${base} "$out" <<'PY'
              import io, json, pathlib, sys, tarfile
              root = pathlib.Path(sys.argv[2])
              files = {}
              with tarfile.open(sys.argv[1]) as archive:
                  manifest = json.load(archive.extractfile('manifest.json'))[0]
                  for layer in manifest['Layers']:
                      with tarfile.open(fileobj=archive.extractfile(layer), mode='r|*') as entries:
                          for entry in entries:
                              name = entry.name.removeprefix('./')
                              if name in ('etc/passwd', 'etc/group'):
                                  files[name] = entries.extractfile(entry).read().decode()
              for name, line in {
                  'etc/passwd': 'tss:x:42434:42434:TPM state:/var/lib/swtpm-localca:/bin/false',
                  'etc/group': 'tss:x:42434:',
              }.items():
                  original = files[name]
                  assert not any(row.split(':')[0] == 'tss' or row.split(':')[2] == '42434'
                                 for row in original.splitlines())
                  (root / name).write_text(original.rstrip('\n') + '\n' + line + '\n')
              PY
              for tool in swtpm swtpm_setup swtpm_ioctl swtpm_localca swtpm_cert; do
                ln -s ${pkgs.swtpm}/bin/"$tool" "$out/usr/bin/$tool"
              done
            '';
          in
          pkgs.dockerTools.buildLayeredImage {
            name = "git.fahrican.com/forge-runner/libvirt-tpm";
            tag = "2026.1-swtpm-0.10.1";
            fromImage = base;
            contents = [ root ];
            fakeRootCommands = ''
              chmod 0700 var/lib/swtpm-localca
              chown 42434:42434 var/lib/swtpm-localca
            '';
            config = {
              Env = [ "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" ];
              Cmd = [ "/bin/bash" ];
              Labels = {
                "org.opencontainers.image.source" = "https://github.com/funforgiven/infra";
                "org.opencontainers.image.description" = "Pinned OpenStack libvirt with software TPM 2.0";
              };
            };
          };
      };
    };
}
