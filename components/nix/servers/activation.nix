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
      apps.enroll-services-credential = {
        program = "${enrollServicesCredential}/bin/enroll-services-credential";
        meta.description = "Enroll a credential in its configured SOPS file";
      };

      apps.enroll-service-host-secrets = {
        program = "${enrollServiceHostSecrets}/bin/enroll-service-host-secrets";
        meta.description = "Install a credential profile on a service host";
      };

      apps.generate-services-credential = {
        program = "${generateServicesCredential}/bin/generate-services-credential";
        meta.description = "Generate and store a credential in SOPS";
      };

      apps.reconcile-services-backblaze = {
        program = "${reconcileServicesBackblaze}/bin/reconcile-services-backblaze";
        meta.description = "Update Backblaze backup settings and application keys";
      };

      apps.initialize-services-restic = {
        program = "${initializeServicesRestic}/bin/initialize-services-restic";
        meta.description = "Initialize Restic repositories for service hosts";
      };

      apps.reconcile-services-telegram = {
        program = "${reconcileServicesTelegram}/bin/reconcile-services-telegram";
        meta.description = "Update Telegram bots and discover private chat IDs";
      };

      apps.reconcile-services-resend = {
        program = "${reconcileServicesResend}/bin/reconcile-services-resend";
        meta.description = "Create or rotate Stalwart's Resend API key";
      };

      apps.enroll-aws-mail-auth = {
        program = "${enrollAwsMailAuth}/bin/enroll-aws-mail-auth";
        meta.description = "Enroll AWS mail credentials and delete their intake files";
      };

      apps.publish-aws-mail-resend = {
        program = "${publishAwsMailResend}/bin/publish-aws-mail-resend";
        meta.description = "Copy the Resend key from SOPS to AWS Secrets Manager";
      };

      packages = {
        enroll-service-host-secrets = enrollServiceHostSecrets;
        enroll-services-credential = enrollServicesCredential;
        generate-services-credential = generateServicesCredential;
        reconcile-services-backblaze = reconcileServicesBackblaze;
        initialize-services-restic = initializeServicesRestic;
        reconcile-services-telegram = reconcileServicesTelegram;
        reconcile-services-resend = reconcileServicesResend;
        aws-mail-credentials = awsMailCredentials;
      };

      checks.services-activation-contract =
        pkgs.runCommandLocal "services-activation-contract-check"
          {
            nativeBuildInputs = [
              python
              pkgs.shellcheck
              runtimeContract
            ];
          }
          ''
            export PYTHONPATH=${./activation}
            export PYTHONPYCACHEPREFIX="$TMPDIR/pycache"
            python -m unittest discover \
              -s ${./activation/tests} -p 'test_*.py'
            python -m compileall -q ${./activation}
            shellcheck \
              ${./activation/enroll-service-host-secrets.sh} \
              ${./activation/enroll-services-credential.sh} \
              ${./activation/generate-services-credential.sh}
            runtime-contract --repository-root ${inputs.self} schema >/dev/null
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
