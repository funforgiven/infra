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
        forge-linux-runner-image =
          let
            runnerBinary = pkgs.fetchurl {
              url = "https://code.forgejo.org/forgejo/runner/releases/download/v13.1.0/forgejo-runner-13.1.0-linux-amd64";
              sha256 = "29dae21e93f0eab5cdf3564008d44603c74770b41a4f4f1aceed172c774bc376";
            };
            runner = pkgs.runCommand "forgejo-runner-13.1.0" { } ''
              install -Dm755 ${runnerBinary} "$out/bin/forgejo-runner"
            '';
            tools = pkgs.buildEnv {
              name = "forge-runner-tools";
              paths = [
                runner
              ]
              ++ (with pkgs; [
                bashInteractive
                coreutils
                curl
                findutils
                gawk
                gnugrep
                gnused
                gitMinimal
                nix
                openssh
                nodejs_24
                python3
                gnumake
                gnutar
                gzip
                xz
                unzip
                which
                cacert
              ]);
              pathsToLink = [
                "/bin"
                "/etc/ssl"
              ];
            };
            closure = pkgs.closureInfo { rootPaths = [ tools ]; };
            root = pkgs.runCommand "forge-runner-root" { } ''
              mkdir -p "$out/etc/nix" "$out/home/runner" "$out/tmp" "$out/workspace" "$out/run/runner" "$out/nix/var/nix"
              printf '%s\n' 'root:x:0:0:root:/root:/bin/bash' 'runner:x:1000:1000:runner:/home/runner:/bin/bash' > "$out/etc/passwd"
              printf '%s\n' 'root:x:0:' 'runner:x:1000:' > "$out/etc/group"
              printf '%s\n' 'hosts: files dns' > "$out/etc/nsswitch.conf"
              printf '%s\n' 'experimental-features = nix-command flakes' 'sandbox = false' 'build-users-group =' 'max-jobs = 2' 'cores = 2' > "$out/etc/nix/nix.conf"
              cp ${closure}/registration "$out/etc/nix/registration"
            '';
          in
          pkgs.dockerTools.buildLayeredImage {
            name = "git.fahrican.com/forge-runner/runner-linux";
            tag = "13.1.0";
            contents = [
              tools
              root
            ];
            fakeRootCommands = ''
              chmod 1777 tmp
              mkdir -p nix/store
              chown 1000:1000 nix/store
              chown -R 1000:1000 home/runner workspace run/runner nix/var/nix
            '';
            config = {
              User = "1000:1000";
              WorkingDir = "/workspace";
              Env = [
                "PATH=/bin"
                "HOME=/home/runner"
                "USER=runner"
                "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
                "NIX_SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
                "GIT_SSL_CAINFO=/etc/ssl/certs/ca-bundle.crt"
              ];
              Cmd = [
                "/bin/forgejo-runner"
                "--version"
              ];
              Labels = {
                "org.opencontainers.image.source" = "https://github.com/funforgiven/infra";
                "org.opencontainers.image.description" =
                  "Unprivileged Forgejo Actions runner for one disposable Kubernetes job";
              };
            };
          };
      };
    };
}
