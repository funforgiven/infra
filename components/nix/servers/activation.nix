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
      reconcileServicesTelegram = reconcilerApplication "reconcile-services-telegram" ./activation/reconcile_services_telegram.py;
      reconcileServicesResend = reconcilerApplication "reconcile-services-resend" ./activation/reconcile_services_resend.py;
      reconcileServicesOpenAI = reconcilerApplication "reconcile-services-openai" ./activation/reconcile_services_openai.py;
      reconcileServicesOperatorNetwork = reconcilerApplication "reconcile-services-operator-network" ./activation/reconcile_services_operator_network.py;
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

      apps.reconcile-services-telegram = {
        program = "${reconcileServicesTelegram}/bin/reconcile-services-telegram";
        meta.description = "Reconcile Telegram metadata and discover private chat targets into SOPS";
      };

      apps.reconcile-services-resend = {
        program = "${reconcileServicesResend}/bin/reconcile-services-resend";
        meta.description = "Create or rotate the domain-scoped Stalwart Resend key into SOPS";
      };

      apps.reconcile-services-openai = {
        program = "${reconcileServicesOpenAI}/bin/reconcile-services-openai";
        meta.description = "Issue the least-privilege Hermes OpenAI key directly into SOPS";
      };

      apps.reconcile-services-operator-network = {
        program = "${reconcileServicesOperatorNetwork}/bin/reconcile-services-operator-network";
        meta.description = "Discover and encrypt the operator mail-management host CIDR";
      };

      apps.services-activation-preflight = {
        program = "${servicesActivationPreflight}/bin/services-activation-preflight";
        meta.description = "Verify credential ciphertext, promotions, and signed clean state before activation";
      };

      packages = {
        advance-services-activation = advanceServicesActivation;
        enroll-service-host-secrets = enrollServiceHostSecrets;
        enroll-services-credential = enrollServicesCredential;
        generate-services-credential = generateServicesCredential;
        reconcile-services-backblaze = reconcileServicesBackblaze;
        reconcile-services-telegram = reconcileServicesTelegram;
        reconcile-services-resend = reconcileServicesResend;
        reconcile-services-openai = reconcileServicesOpenAI;
        reconcile-services-operator-network = reconcileServicesOperatorNetwork;
        services-activation-preflight = servicesActivationPreflight;
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
            python -m py_compile ${./activation/reconcile_services_telegram.py}
            python -m py_compile ${./activation/reconcile_services_resend.py}
            python -m py_compile ${./activation/reconcile_services_openai.py}
            python -m py_compile ${./activation/reconcile_services_operator_network.py}
            python -m py_compile ${./activation/sops_credentials.py}
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
            rg --fixed-strings --quiet 'keyName' \
              ${./activation/reconcile_services_backblaze.py}
            rg --fixed-strings --quiet 'api.responses.write' \
              ${./activation/reconcile_services_openai.py}
            if rg --quiet 'print\([^)]*(administration_key|value)|OPENAI_API_KEY\.key' \
              ${./activation/reconcile_services_openai.py} \
              ${inputs.self}/deployments/homelab/cloud/services/ACTIVATION.md; then
              echo 'OpenAI runtime key material may escape the SOPS reconciler.' >&2
              exit 1
            fi
            if rg --quiet 'prompt_value|R2_ENDPOINT|cloudflarestorage' \
              ${./activation/enroll-service-host-secrets.sh} \
              ${./README.md} \
              ${inputs.self}/deployments/homelab/cloud/services/ACTIVATION.md; then
              echo 'Obsolete interactive or Cloudflare R2 host enrollment remains.' >&2
              exit 1
            fi
            touch "$out"
          '';
    };
}
