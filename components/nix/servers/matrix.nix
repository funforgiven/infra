_: {
  perSystem =
    { pkgs, ... }:
    let
      source = ../../cloud/services/matrix;
      python = pkgs.python3.withPackages (ps: [
        ps.pyyaml
        ps.aiohttp
        (ps.matrix-nio.override { withVodozemac = true; })
        ps.boto3
      ]);
      accessPython = pkgs.python3.withPackages (ps: [
        ps.pyyaml
        ps.python-openstackclient
        ps.python-magnumclient
      ]);
      proxyConfig = pkgs.runCommand "matrix-proxy-config" { } ''
        mkdir -p "$out/etc"
        substitute ${source}/nginx.conf "$out/etc/matrix-nginx.conf" \
          --subst-var-by elementRoot ${pkgs.element-web}
      '';
      root = pkgs.runCommand "matrix-container-root" { } ''
        mkdir -p "$out/etc" "$out/tmp" "$out/var/lib/matrix"
        printf '%s\n' 'matrix:x:1000:1000:Matrix:/var/lib/matrix:/bin/false' > "$out/etc/passwd"
        printf '%s\n' 'matrix:x:1000:' > "$out/etc/group"
      '';
      image = pkgs.dockerTools.buildLayeredImage {
        name = "git.fahrican.com/forge-runner/matrix-runtime";
        tag = "1.0.0";
        contents = [
          python
          pkgs.matrix-synapse
          pkgs.matrix-authentication-service
          pkgs.postgresql_17
          pkgs.nginx
          pkgs.squid
          pkgs.cacert
          pkgs.coreutils
          pkgs.bash
          pkgs.curl
          pkgs.kubectl
          pkgs.element-web
          proxyConfig
          root
        ];
        fakeRootCommands = ''
          chmod 1777 tmp
          chown 1000:1000 var/lib/matrix
        '';
        config = {
          User = "1000:1000";
          Env = [
            "PATH=/bin"
            "HOME=/var/lib/matrix"
            "PYTHONDONTWRITEBYTECODE=1"
            "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
          ];
          Cmd = [
            "python"
            "/scripts/relay.py"
          ];
        };
      };
    in
    {
      packages.matrix-runtime-image = image;
      packages.matrix-python = python;
      apps.matrix-admin = {
        meta.description = "Enroll and qualify the private Matrix service";
        program = "${
          pkgs.writeShellApplication {
            name = "matrix-admin";
            runtimeInputs = [
              pkgs.kubectl
              pkgs.sops
              pkgs.openssl
              pkgs.skopeo
              pkgs.gitMinimal
              pkgs.matrix-authentication-service
            ];
            text = ''exec ${python}/bin/python ${source}/admin.py "$@"'';
          }
        }/bin/matrix-admin";
      };
      apps.matrix-access = {
        meta.description = "Run a command with an ephemeral homelab kubeconfig";
        program = "${
          pkgs.writeShellApplication {
            name = "matrix-access";
            runtimeInputs = [
              pkgs.openssh
              pkgs.kubectl
              accessPython
            ];
            text = ''exec ${accessPython}/bin/python ${source}/access.py "$@"'';
          }
        }/bin/matrix-access";
      };
      apps.matrix-qualify-local = {
        meta.description = "Test a disposable Matrix stack and encrypted recovery";
        program = "${
          pkgs.writeShellApplication {
            name = "matrix-qualify-local";
            runtimeInputs = [
              pkgs.postgresql_17
              pkgs.matrix-synapse
              pkgs.matrix-authentication-service
              pkgs.nginx
              pkgs.cacert
            ];
            text = ''
              export SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
              exec ${python}/bin/python ${source}/tests/integration.py
            '';
          }
        }/bin/matrix-qualify-local";
      };
      checks.matrix-alert-relay = pkgs.runCommand "matrix-alert-relay-check" { } ''
        export PYTHONDONTWRITEBYTECODE=1
        ${python}/bin/python -m unittest discover -s ${source}/tests -v
        touch "$out"
      '';
    };
}
