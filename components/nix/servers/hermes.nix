{
  inputs,
  lib,
  ...
}:
let
  hermesSoul = ''
    You are the private infrastructure and personal assistant for this homelab.

    Infrastructure changes must be proposed as reviewable Git changes and applied
    through the repository's OpenTofu, Flux, or NixOS reconciliation paths. Never
    print, persist, or transmit credentials. Ask for explicit confirmation before
    any purchase, checkout, paid subscription, or destructive operation.

    No web-search service or external knowledge store is configured. Do not claim
    that search, semantic retrieval, embeddings, Hindsight, or a vector database
    is available.
  '';
in
{
  nixos.modules.services-hermes =
    {
      config,
      pkgs,
      ...
    }:
    let
      # The pinned upstream source imports this first-party top-level module
      # from hermes_cli.plugins, but its pyproject omits the file from
      # setuptools.py-modules. Keep the compatibility boundary isolated until
      # the upstream Nix package ships it in the sealed Python environment.
      registrationLifecycle = pkgs.runCommand "hermes-registration-lifecycle" { } ''
        install -Dm0444 \
          ${inputs.hermes-agent}/registration_lifecycle.py \
          "$out/${pkgs.python312.sitePackages}/registration_lifecycle.py"
      '';
      upstreamHermesPackage =
        inputs.hermes-agent.packages.${pkgs.stdenv.hostPlatform.system}.default.override
          {
            extraPythonPackages = [ registrationLifecycle ];
          };
      hermesPackage = upstreamHermesPackage.overrideAttrs (old: {
        doInstallCheck = true;
        installCheckPhase = (old.installCheckPhase or "") + ''
          PYTHONPATH=${registrationLifecycle}/${pkgs.python312.sitePackages} \
            ${upstreamHermesPackage.hermesVenv}/bin/python3 -c \
              'import registration_lifecycle; import telegram; from hermes_cli import plugins'
        '';
      });
    in
    {
      imports = [ inputs.hermes-agent.nixosModules.default ];

      services.hermes-agent = {
        enable = true;
        package = hermesPackage;
        addToSystemPackages = true;
        extraPackages = [
          pkgs.curl
          pkgs.gitMinimal
          pkgs.jq
          pkgs.ripgrep
        ];
        restart = "on-failure";
        restartSec = 15;
        environmentFiles = [
          "/var/lib/hermes-bootstrap/openai.env"
          "/var/lib/hermes-bootstrap/telegram.env"
        ];
        settings = {
          agent.disabled_toolsets = [ "web" ];
          model = {
            provider = "openai-api";
            default = "gpt-5.6-luna";
          };
          memory = {
            memory_enabled = false;
            user_profile_enabled = false;
          };
          platforms.telegram.extra.status_indicator = true;
          terminal = {
            backend = "local";
            timeout = 180;
          };
        };
      };

      system.activationScripts.hermes-declarative-soul = lib.stringAfter [ "hermes-agent-setup" ] ''
        install -o hermes -g hermes -m 0640 \
          ${pkgs.writeText "hermes-soul.md" hermesSoul} \
          /var/lib/hermes/.hermes/SOUL.md
      '';

      # The independently revocable OpenAI key and Telegram credentials are
      # enrolled from separate sources into separate root-only files. The
      # gateway remains dormant until both boundaries have been populated.
      systemd.services.hermes-agent.unitConfig.ConditionPathExists = [
        "/var/lib/hermes-bootstrap/openai.env"
        "/var/lib/hermes-bootstrap/telegram.env"
      ];

      systemd.tmpfiles.rules = [
        "d /var/lib/hermes-bootstrap 0700 root root - -"
        "r /var/lib/hermes-bootstrap/integrations.env - - - - -"
      ];

      servicesPlatform.backup = {
        paths = [
          "/var/lib/hermes"
          "/var/lib/hermes-bootstrap"
        ];
        tag = "hermes-state";
      };

      servicesPlatform.alerting.units = [
        "hermes-agent"
        "restic-backups-service-state"
      ];

      networking.firewall.allowedTCPPorts = [ ];

      assertions = [
        {
          assertion = config.services.hermes-agent.settings.model.provider == "openai-api";
          message = "Hermes must use the independently revocable direct OpenAI API provider.";
        }
        {
          assertion = config.services.hermes-agent.settings.model.default == "gpt-5.6-luna";
          message = "Hermes must retain gpt-5.6-luna as its default model.";
        }
        {
          assertion = config.services.hermes-agent.settings.memory.memory_enabled == false;
          message = "Semantic or autonomous Hermes memory must remain disabled.";
        }
        {
          assertion = lib.elem "web" config.services.hermes-agent.settings.agent.disabled_toolsets;
          message = "Hermes web search and extraction tools must remain disabled.";
        }
      ];
    };
}
