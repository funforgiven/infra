_: {
  perSystem =
    {
      pkgs,
      lib,
      system,
      ...
    }:
    {
      packages = lib.optionalAttrs (system == "x86_64-linux") rec {
        forge-linux-runner-image =
          let
            runnerBinary = pkgs.fetchurl {
              url = "https://code.forgejo.org/forgejo/runner/releases/download/v13.1.0/forgejo-runner-13.1.0-linux-amd64";
              sha256 = "29dae21e93f0eab5cdf3564008d44603c74770b41a4f4f1aceed172c774bc376";
            };
            runner = pkgs.runCommand "forgejo-runner-13.1.0" { } ''
              install -Dm755 ${runnerBinary} "$out/bin/forgejo-runner"
            '';
            # pigz keeps the gzip format and cache version.
            parallelGzip = pkgs.writeShellScriptBin "gzip" ''
              exec ${pkgs.pigz}/bin/pigz --processes 3 --fast "$@"
            '';
            tools = pkgs.buildEnv {
              name = "forge-runner-tools";
              paths = [
                runner
                (lib.hiPrio parallelGzip)
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
              mkdir -p "$out/etc/nix" "$out/home/runner" "$out/tmp" "$out/workspace" "$out/run/runner" "$out/nix/var/nix" "$out/nix/var/log/nix/drvs"
              printf '%s\n' 'root:x:0:0:root:/root:/bin/bash' 'runner:x:1000:1000:runner:/home/runner:/bin/bash' > "$out/etc/passwd"
              printf '%s\n' 'root:x:0:' 'runner:x:1000:' > "$out/etc/group"
              printf '%s\n' 'hosts: files dns' > "$out/etc/nsswitch.conf"
              printf '%s\n' 'experimental-features = nix-command flakes' 'sandbox = false' 'build-users-group =' 'max-jobs = 2' 'cores = 2' > "$out/etc/nix/nix.conf"
              cp ${closure}/registration "$out/etc/nix/registration"
            '';
          in
          pkgs.dockerTools.buildLayeredImage {
            name = "git.fahrican.com/forge-runner/runner-linux";
            tag = "13.1.0-gzip.1";
            contents = [
              tools
              root
            ];
            fakeRootCommands = ''
              chmod 1777 tmp
              mkdir -p nix/store
              chown 1000:1000 nix/store
              chown -R 1000:1000 home/runner workspace run/runner nix/var/nix nix/var/log/nix
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

        # Only the build cache runs patched code: upstream keys caches globally
        # by key/version, so another repository could read or evict entries.
        # Runner jobs keep the upstream binary above.
        forge-cache-backend = pkgs.forgejo-runner.overrideAttrs (_: {
          version = "13.1.0";
          src = pkgs.fetchFromGitea {
            domain = "code.forgejo.org";
            owner = "forgejo";
            repo = "runner";
            rev = "v13.1.0";
            hash = "sha256-0LVia4B9n2zuuHDGFnBVM1mrbI7XBhMfy25kRSN5/WQ=";
          };
          vendorHash = "sha256-2QwltVOR6MJO8rLNgktN1ulvP0YrnqQorNnfJXzRmJs=";
          patches = [ ../../homelab/services/forge/runner-cache-isolation.patch ];
          ldflags = [
            "-s"
            "-w"
            "-X code.forgejo.org/forgejo/runner/v13/internal/pkg/ver.version=v13.1.0+cache-isolation.1"
          ];
          # The patch only touches the cache server; test that package alone.
          # Handler tests discover an outbound address, absent in the sandbox.
          preCheck = ''
            substituteInPlace act/artifactcache/handler_test.go \
              --replace-fail 'StartHandler(dir, "", 0,' 'StartHandler(dir, "127.0.0.1", 0,'
          '';
          checkPhase = ''
            runHook preCheck
            go test -p "$NIX_BUILD_CORES" -count=1 ./act/artifactcache
            runHook postCheck
          '';
          # No git wrapper: the cache server never runs jobs.
          postInstall = ''
            mv "$out/bin/runner" "$out/bin/forgejo-runner"
          '';
        });

        forge-cache-image =
          let
            tools = pkgs.buildEnv {
              name = "forge-cache-tools";
              paths = [
                forge-cache-backend
                pkgs.python3
                pkgs.cacert
              ];
              pathsToLink = [
                "/bin"
                "/etc/ssl"
              ];
            };
            root = pkgs.runCommand "forge-cache-root" { } ''
              mkdir -p "$out/etc" "$out/tmp" "$out/var/lib/forge-cache"
              printf '%s\n' 'cache:x:1000:1000:Cache:/var/lib/forge-cache:/bin/false' > "$out/etc/passwd"
              printf '%s\n' 'cache:x:1000:' > "$out/etc/group"
            '';
          in
          pkgs.dockerTools.buildLayeredImage {
            name = "git.fahrican.com/forge-runner/cache";
            tag = "13.1.0-isolation.2";
            contents = [
              tools
              root
            ];
            fakeRootCommands = ''
              chmod 1777 tmp
              chown 1000:1000 var/lib/forge-cache
            '';
            config = {
              User = "1000:1000";
              WorkingDir = "/var/lib/forge-cache";
              Env = [
                "PATH=/bin"
                "HOME=/var/lib/forge-cache"
                "PYTHONDONTWRITEBYTECODE=1"
              ];
              Cmd = [
                "/bin/forgejo-runner"
                "--version"
              ];
              Labels = {
                "org.opencontainers.image.source" = "https://github.com/funforgiven/infra";
                "org.opencontainers.image.description" =
                  "Private Forgejo build cache backend with scoped cache isolation fixes";
              };
            };
          };
      };
    };
}
