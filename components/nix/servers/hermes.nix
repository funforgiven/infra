{
  inputs,
  lib,
  ...
}:
let
  hermesSoul = ''
    You are the private infrastructure and knowledge assistant for this homelab.

    Infrastructure changes must be proposed as reviewable Git changes and applied
    through the repository's OpenTofu, Flux, or NixOS reconciliation paths. Never
    print, persist, or transmit credentials. Ask for explicit confirmation before
    any purchase, checkout, paid subscription, or destructive operation.

    Karakeep is the initial knowledge system. Use its full-text search and explicit
    tags/lists only. Do not claim that semantic retrieval, embeddings, Hindsight,
    or a vector database are active unless the repository later enables them.
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
      karakeepMcpImage = pkgs.dockerTools.pullImage {
        imageName = "ghcr.io/karakeep-app/karakeep-mcp";
        imageDigest = "sha256:8b2f784ad0ffc5dbc75485f125e23fdd033d4c9d05d680e8f090b6b6aa93c2f6";
        hash = "sha256-apeVCJuH4vWehL8rTKG+dq5552Rj5DbjR49Hnq1uQRw=";
        finalImageName = "ghcr.io/karakeep-app/karakeep-mcp";
        finalImageTag = "0.32.0";
      };
      karakeepMcp =
        pkgs.runCommand "karakeep-mcp-0.32.0"
          {
            nativeBuildInputs = [
              pkgs.gnutar
              pkgs.jq
              pkgs.makeWrapper
            ];
          }
          ''
            image_root="$TMPDIR/image"
            unpacked_root="$TMPDIR/root"
            mkdir -p "$image_root" "$unpacked_root" "$out/lib/karakeep-mcp" "$out/bin"
            tar --extract --file ${karakeepMcpImage} --directory "$image_root"

            while IFS= read -r layer; do
              tar --extract --file "$image_root/$layer" --directory "$unpacked_root"
            done < <(jq --raw-output '.[0].Layers[]' "$image_root/manifest.json")

            install -m 0444 \
              "$unpacked_root/app/apps/mcp/index.js" \
              "$out/lib/karakeep-mcp/index.js"
            makeWrapper ${pkgs.nodejs_24}/bin/node "$out/bin/karakeep-mcp" \
              --add-flags "$out/lib/karakeep-mcp/index.js"
          '';
    in
    {
      imports = [ inputs.hermes-agent.nixosModules.default ];

      services.hermes-agent = {
        enable = true;
        addToSystemPackages = true;
        extraPackages = [
          pkgs.curl
          pkgs.gitMinimal
          pkgs.jq
          pkgs.ripgrep
        ];
        restart = "on-failure";
        restartSec = 15;
        environment.SEARXNG_URL = "https://search.fahrican.com";
        environmentFiles = [
          "/var/lib/hermes-bootstrap/openai.env"
          "/var/lib/hermes-bootstrap/integrations.env"
        ];
        mcpServers.karakeep = {
          command = "${karakeepMcp}/bin/karakeep-mcp";
          env = {
            KARAKEEP_API_ADDR = "https://keep.fahrican.com";
            KARAKEEP_API_KEY = "\${KARAKEEP_API_KEY}";
          };
          connect_timeout = 30;
          timeout = 120;
        };
        settings = {
          model = {
            provider = "openai-api";
            default = "gpt-5.6-luna";
          };
          memory = {
            memory_enabled = false;
            user_profile_enabled = false;
          };
          platforms.telegram.extra.status_indicator = true;
          web.search_backend = "searxng";
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

      # The independently revocable OpenAI key and integration credentials are
      # enrolled from separate sources into separate root-only files. The
      # gateway remains dormant until both boundaries have been populated.
      systemd.services.hermes-agent.unitConfig.ConditionPathExists = [
        "/var/lib/hermes-bootstrap/openai.env"
        "/var/lib/hermes-bootstrap/integrations.env"
      ];

      systemd.tmpfiles.rules = [
        "d /var/lib/hermes-bootstrap 0700 root root - -"
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
          message = "Semantic or autonomous Hermes memory must remain disabled during the Karakeep full-text phase.";
        }
      ];
    };
}
