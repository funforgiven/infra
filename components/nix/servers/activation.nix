{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (pythonPackages: [ pythonPackages.pyyaml ]);
      awsMailConfiguration = inputs.self.nixosConfigurations.mail-aws.config;
      runtimeContract = pkgs.writeShellApplication {
        name = "runtime-contract";
        runtimeInputs = [ pkgs.gitMinimal ];
        text = ''
          exec ${python}/bin/python ${./activation/runtime_contract.py} "$@"
        '';
      };
      advanceServicesActivationEdit = pkgs.writeShellApplication {
        name = "advance-services-activation-edit";
        runtimeInputs = [ python ];
        text = ''
          exec ${python}/bin/python ${./activation/advance_services_activation.py} "$@"
        '';
      };
      enrollServicesCredential = pkgs.writeShellApplication {
        name = "enroll-services-credential";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.jq
          pkgs.ripgrep
          pkgs.sops
          runtimeContract
        ];
        text = builtins.readFile ./activation/enroll-services-credential.sh;
      };
      generateServicesCredential = pkgs.writeShellApplication {
        name = "generate-services-credential";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.jq
          pkgs.openssl
          pkgs.ripgrep
          pkgs.sops
          runtimeContract
        ];
        text = builtins.readFile ./activation/generate-services-credential.sh;
      };
      reconcilerApplication =
        name: script:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = [
            pkgs.gitMinimal
            pkgs.sops
          ];
          text = ''
            export PYTHONPATH=${./activation}
            exec ${python}/bin/python ${script} "$@"
          '';
        };
      reconcileServicesBackblaze = reconcilerApplication "reconcile-services-backblaze" ./activation/reconcile_services_backblaze.py;
      initializeServicesRestic = pkgs.writeShellApplication {
        name = "initialize-services-restic";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.restic
          pkgs.sops
        ];
        text = ''
          export PYTHONPATH=${./activation}
          exec ${python}/bin/python ${./activation/initialize_services_restic.py} "$@"
        '';
      };
      reconcileServicesTelegram = reconcilerApplication "reconcile-services-telegram" ./activation/reconcile_services_telegram.py;
      reconcileServicesResend = reconcilerApplication "reconcile-services-resend" ./activation/reconcile_services_resend.py;
      reconcileServicesOperatorNetwork = reconcilerApplication "reconcile-services-operator-network" ./activation/reconcile_services_operator_network.py;
      awsMailCredentials = pkgs.writeShellApplication {
        name = "aws-mail-credentials";
        runtimeInputs = [
          pkgs.awscli2
          pkgs.gitMinimal
          pkgs.sops
        ];
        text = ''
          export PYTHONPATH=${./activation}
          exec ${python}/bin/python ${./activation/aws_mail_credentials.py} "$@"
        '';
      };
      enrollAwsMailAuth = pkgs.writeShellApplication {
        name = "enroll-aws-mail-auth";
        text = ''
          exec ${awsMailCredentials}/bin/aws-mail-credentials provisioning "$@"
        '';
      };
      publishAwsMailResend = pkgs.writeShellApplication {
        name = "publish-aws-mail-resend";
        text = ''
          exec ${awsMailCredentials}/bin/aws-mail-credentials resend "$@"
        '';
      };
      servicesActivationPreflight = pkgs.writeShellApplication {
        name = "services-activation-preflight";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.ripgrep
          pkgs.sops
          runtimeContract
        ];
        text = builtins.readFile ./activation/services-activation-preflight.sh;
      };
      advanceServicesActivation = pkgs.writeShellApplication {
        name = "advance-services-activation";
        runtimeInputs = [
          advanceServicesActivationEdit
          pkgs.gitMinimal
        ];
        text = builtins.readFile ./activation/advance-services-activation.sh;
      };
      enrollServiceHostSecrets = pkgs.writeShellApplication {
        name = "enroll-service-host-secrets";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.openssh
          pkgs.sops
          runtimeContract
        ];
        text = builtins.readFile ./activation/enroll-service-host-secrets.sh;
      };
    in
    {
      apps.advance-services-activation = {
        program = "${advanceServicesActivation}/bin/advance-services-activation";
        meta.description = "Enable one service activation stage in Git-managed Flux manifests";
      };

      apps.enroll-services-credential = {
        program = "${enrollServicesCredential}/bin/enroll-services-credential";
        meta.description = "Enroll one contract-defined credential into its SOPS document";
      };

      apps.enroll-service-host-secrets = {
        program = "${enrollServiceHostSecrets}/bin/enroll-service-host-secrets";
        meta.description = "Stream a validated root-only credential profile to a service host";
      };

      apps.generate-services-credential = {
        program = "${generateServicesCredential}/bin/generate-services-credential";
        meta.description = "Generate one contract-defined secret directly into SOPS ciphertext";
      };

      apps.reconcile-services-backblaze = {
        program = "${reconcileServicesBackblaze}/bin/reconcile-services-backblaze";
        meta.description = "Reconcile scoped Backblaze backup keys directly into SOPS";
      };

      apps.initialize-services-restic = {
        program = "${initializeServicesRestic}/bin/initialize-services-restic";
        meta.description = "Initialize host Restic prefixes through their scoped Backblaze keys";
      };

      apps.reconcile-services-telegram = {
        program = "${reconcileServicesTelegram}/bin/reconcile-services-telegram";
        meta.description = "Reconcile Telegram metadata and discover private chat targets into SOPS";
      };

      apps.reconcile-services-resend = {
        program = "${reconcileServicesResend}/bin/reconcile-services-resend";
        meta.description = "Create or rotate the domain-scoped Stalwart Resend key into SOPS";
      };

      apps.reconcile-services-operator-network = {
        program = "${reconcileServicesOperatorNetwork}/bin/reconcile-services-operator-network";
        meta.description = "Discover and encrypt the operator mail-management host CIDR";
      };

      apps.services-activation-preflight = {
        program = "${servicesActivationPreflight}/bin/services-activation-preflight";
        meta.description = "Verify phase-appropriate credentials, promotions, and signed clean state before activation";
      };

      apps.enroll-aws-mail-auth = {
        program = "${enrollAwsMailAuth}/bin/enroll-aws-mail-auth";
        meta.description = "Enroll the final AWS mail provider pair into SOPS and clear its intake files";
      };

      apps.publish-aws-mail-resend = {
        program = "${publishAwsMailResend}/bin/publish-aws-mail-resend";
        meta.description = "Publish the existing Resend key directly from SOPS to AWS Secrets Manager";
      };

      packages = {
        advance-services-activation = advanceServicesActivation;
        enroll-service-host-secrets = enrollServiceHostSecrets;
        enroll-services-credential = enrollServicesCredential;
        generate-services-credential = generateServicesCredential;
        reconcile-services-backblaze = reconcileServicesBackblaze;
        initialize-services-restic = initializeServicesRestic;
        reconcile-services-telegram = reconcileServicesTelegram;
        reconcile-services-resend = reconcileServicesResend;
        reconcile-services-operator-network = reconcileServicesOperatorNetwork;
        services-activation-preflight = servicesActivationPreflight;
        aws-mail-credentials = awsMailCredentials;
      };

      checks.services-activation-contract =
        pkgs.runCommandLocal "services-activation-contract-check"
          {
            nativeBuildInputs = [
              python
              pkgs.ripgrep
              pkgs.shellcheck
              runtimeContract
            ];
          }
          ''
            export PYTHONPATH=${./activation}
            export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
            python -m unittest discover \
              -s ${./activation/tests} -p 'test_*.py'
            python -m py_compile ${./activation/advance_services_activation.py}
            python -m py_compile ${./activation/reconcile_services_backblaze.py}
            python -m py_compile ${./activation/initialize_services_restic.py}
            python -m py_compile ${./activation/reconcile_services_telegram.py}
            python -m py_compile ${./activation/reconcile_services_resend.py}
            python -m py_compile ${./activation/reconcile_services_operator_network.py}
            python -m py_compile ${./activation/sops_credentials.py}
            python -m py_compile ${./activation/aws_mail_credentials.py}
            shellcheck \
              ${./activation/advance-services-activation.sh} \
              ${./activation/enroll-service-host-secrets.sh} \
              ${./activation/enroll-services-credential.sh} \
              ${./activation/generate-services-credential.sh} \
              ${./activation/services-activation-preflight.sh}
            runtime-contract --repository-root ${inputs.self} schema >/dev/null
            rg --fixed-strings --quiet 'provider = "openai-api";' \
              ${./hermes.nix}
            rg --fixed-strings --quiet 'default = "gpt-5.6-luna";' \
              ${./hermes.nix}
            rg --fixed-strings --quiet 'agent.disabled_toolsets = [ "web" ];' \
              ${./hermes.nix}
            if rg --fixed-strings --quiet 'http = {' \
              ${./home-assistant.nix}; then
              echo 'Home Assistant HTTP settings must not return to ignored YAML.' >&2
              exit 1
            fi
            rg --fixed-strings --quiet \
              'Home Assistant OS onboarding' \
              ${inputs.self}/deployments/homelab/cloud/manual-exceptions.yaml
            rg --fixed-strings --quiet \
              'services/hosts/home-assistant/' \
              ${inputs.self}/deployments/homelab/cloud/services/ACTIVATION.md
            if rg --quiet 'openai-codex|auth\.json|device-code|device-auth' \
              ${./hermes.nix} \
              ${./README.md} \
              ${inputs.self}/deployments/homelab/cloud/services/ACTIVATION.md \
              ${inputs.self}/deployments/homelab/cloud/manual-exceptions.yaml; then
              echo 'Obsolete Hermes OAuth configuration remains.' >&2
              exit 1
            fi
            rg --fixed-strings --quiet 'generated-key-file "$key"' \
              ${./activation/generate-services-credential.sh}
            rg --fixed-strings --quiet 'managed-key-file "$key"' \
              ${./activation/enroll-service-host-secrets.sh}
            rg --fixed-strings --quiet 'source_file="$intake_directory/$key.key"' \
              ${./activation/enroll-services-credential.sh}
            rg --fixed-strings --quiet 'provisioned-key-file' \
              ${./activation/runtime_contract.py}
            rg --fixed-strings --quiet \
              "yq eval --unwrapScalar '.endpoints.identity.auth.admin.password' -" \
              ${./image-promotion.nix}
            rg --fixed-strings --quiet 'os.O_NOFOLLOW' \
              ${./activation/aws_mail_credentials.py}
            rg --fixed-strings --quiet 'stdout=subprocess.DEVNULL' \
              ${./activation/aws_mail_credentials.py}
            if rg --fixed-strings --quiet 'excludeShellChecks' \
              ${./mail-aws.nix}; then
              echo 'Stalwart shell checks must not be suppressed.' >&2
              exit 1
            fi
            test "$(rg --count 'EnvironmentFile = deploymentEnvironment;' \
              ${./mail-aws.nix})" = 2
            rg --fixed-strings --quiet 'STALWART_PASSWORD="$(<' \
              ${./mail-aws.nix}
            rg --line-regexp --quiet '[[:space:]]+export STALWART_PASSWORD' \
              ${./mail-aws.nix}
            if rg --fixed-strings --quiet \
              'export STALWART_PASSWORD="$(' ${./mail-aws.nix}; then
              echo 'Stalwart password assignment masks read failures from ShellCheck.' >&2
              exit 1
            fi
            rg --fixed-strings --quiet \
              'https://truststore.pki.rds.amazonaws.com/eu-central-1/eu-central-1-bundle.pem' \
              ${./mail-aws.nix}
            rg --fixed-strings --quiet \
              'sha256-VqDK4ES2zEM5cdlkNHQBaSqS6gKU45J1Oj69ruVNi4Q=' \
              ${./mail-aws.nix}
            rg --fixed-strings --quiet 'trap stop_server EXIT' \
              ${./mail-aws.nix}
            rg --fixed-strings --quiet 'export STALWART_RECOVERY_MODE=true' \
              ${./mail-aws.nix}
            test "$(rg --count '^[[:space:]]+start_server$' \
              ${./mail-aws.nix})" = 2
            rg --fixed-strings --quiet \
              'stalwart-cli query Account' ${./mail-aws.nix}
            rg --fixed-strings --quiet \
              '{"0":{"@type":"Password"' ${./mail-aws.nix}
            if rg --fixed-strings --quiet '"credentialId"' \
              ${./mail-aws.nix}; then
              echo 'Stalwart credential IDs are server-owned.' >&2
              exit 1
            fi
            if rg --fixed-strings --quiet '"credentials":[' \
              ${./mail-aws.nix}; then
              echo 'Stalwart registry list fields must use numeric-keyed objects.' >&2
              exit 1
            fi
            test "$(rg --count '"bind":\{"0":"\[::\]:' \
              ${./mail-aws.nix})" = 5
            if rg --fixed-strings --quiet '"bind":[' \
              ${./mail-aws.nix}; then
              echo 'Stalwart listener bind fields must use numeric-keyed objects.' >&2
              exit 1
            fi
            rg --fixed-strings --quiet \
              '"match":{"0":{"if":"is_local_domain(rcpt_domain)"' \
              ${./mail-aws.nix}
            if rg --fixed-strings --quiet '"route":{"match":[' \
              ${./mail-aws.nix}; then
              echo 'Stalwart expression match fields must use numeric-keyed objects.' >&2
              exit 1
            fi
            if rg --fixed-strings --quiet '"allowInvalidCerts":true' \
              ${./mail-aws.nix}; then
              echo 'Stalwart contains a TLS certificate-validation bypass.' >&2
              exit 1
            fi
            rg --fixed-strings --quiet 'keyName' \
              ${./activation/reconcile_services_backblaze.py}
            if rg --quiet 'prompt_value|R2_ENDPOINT|cloudflarestorage' \
              ${./activation/enroll-service-host-secrets.sh} \
              ${./README.md} \
              ${inputs.self}/deployments/homelab/cloud/services/ACTIVATION.md; then
              echo 'Obsolete interactive or Cloudflare R2 host enrollment remains.' >&2
              exit 1
            fi
            touch "$out"
          '';

      checks.services-aws-mail-evaluation =
        pkgs.runCommandLocal "services-aws-mail-evaluation-check" { }
          ''
            test ${pkgs.lib.escapeShellArg awsMailConfiguration.nixpkgs.hostPlatform.system} = aarch64-linux
            test ${pkgs.lib.escapeShellArg awsMailConfiguration.systemd.services.stalwart.serviceConfig.User} = stalwart
            test ${pkgs.lib.escapeShellArg awsMailConfiguration.systemd.services.stalwart-secrets.serviceConfig.Type} = oneshot
            test ${if awsMailConfiguration.services.amazon-ssm-agent.enable then "1" else "0"} = 1
            test ${if awsMailConfiguration.services.openssh.openFirewall then "1" else "0"} = 0
            test ${toString (builtins.length awsMailConfiguration.swapDevices)} = 1
            test ${pkgs.lib.escapeShellArg (builtins.head awsMailConfiguration.swapDevices).device} = /swapfile
            test ${toString (builtins.head awsMailConfiguration.swapDevices).size} = 2048
            test ${toString (builtins.length awsMailConfiguration.security.pki.certificateFiles)} = 1
            test ${
              if
                builtins.elem "d /etc/stalwart-bootstrap 0750 root root -" awsMailConfiguration.systemd.tmpfiles.rules
              then
                "1"
              else
                "0"
            } = 1
            test ${
              if
                builtins.elem "z /etc/stalwart-bootstrap/aws.env 0600 root root -" awsMailConfiguration.systemd.tmpfiles.rules
              then
                "1"
              else
                "0"
            } = 1
            test ${
              if
                awsMailConfiguration.networking.firewall.allowedTCPPorts == [
                  25
                  443
                  465
                  587
                  993
                ]
              then
                "1"
              else
                "0"
            } = 1
            touch "$out"
          '';
    };
}
