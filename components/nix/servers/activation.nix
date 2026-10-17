{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.withPackages (pythonPackages: [ pythonPackages.pyyaml ]);
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
        name: script: extraInputs:
        pkgs.writeShellApplication {
          inherit name;
          runtimeInputs = [
            pkgs.gitMinimal
            pkgs.sops
          ]
          ++ extraInputs;
          text = ''
            export PYTHONPATH=${./activation}
            exec ${python}/bin/python ${script} "$@"
          '';
        };
      reconcileServicesBackblaze =
        reconcilerApplication "reconcile-services-backblaze" ./activation/reconcile_services_backblaze.py
          [ ];
      initializeServicesRestic =
        reconcilerApplication "initialize-services-restic" ./activation/initialize_services_restic.py
          [ pkgs.restic ];
      reconcileServicesTelegram =
        reconcilerApplication "reconcile-services-telegram" ./activation/reconcile_services_telegram.py
          [ ];
      reconcileServicesResend =
        reconcilerApplication "reconcile-services-resend" ./activation/reconcile_services_resend.py
          [ ];
      awsMailCredentials =
        reconcilerApplication "aws-mail-credentials" ./activation/aws_mail_credentials.py
          [ pkgs.awscli2 ];
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

      apps.aws-mail-credentials = {
        program = "${awsMailCredentials}/bin/aws-mail-credentials";
        meta.description = "Enroll AWS mail credentials or copy the Resend key to AWS Secrets Manager";
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
    };
}
