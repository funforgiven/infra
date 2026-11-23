{ inputs, ... }:
{
  perSystem = { pkgs, ... }: {
    packages.codex = pkgs.codex;
  };

  dendritic.nixpkgs.overlays = [
    (_final: prev: {
      codex = inputs.nixpkgs-codex.legacyPackages.${prev.stdenv.hostPlatform.system}.codex;
    })
  ];

  dendritic.nixpkgs.allowUnfreePackages = [ "terraform" ];

  home.gui =
    { config, pkgs, ... }:
    {
      programs.codex.settings = {
        marketplaces.openai-bundled = {
          source_type = "local";
          source = "${config.home.homeDirectory}/.codex/.tmp/bundled-marketplaces/openai-bundled";
        };
        plugins."browser@openai-bundled".enabled = true;
      };

      # Codex scans real version directories in its plugin cache.
      home.file.".codex/plugins/cache/openai-bundled/browser/${pkgs.chatgpt.version}" = {
        source = "${pkgs.chatgpt}/lib/chatgpt/resources/plugins/openai-bundled/plugins/browser";
        recursive = true;
      };
    };

  home.base.imports = [
    (
      {
        config,
        lib,
        pkgs,
        ...
      }:
      let
        python = pkgs.python312;
        terraformMcpServer = pkgs.terraform-mcp-server;
      in
      {
        home.packages = [
          pkgs.awscli2
          pkgs.fd
          pkgs.nodejs
          python
          pkgs.ripgrep
          pkgs.terraform
          pkgs.uv
        ];

        programs.codex = {
          enable = true;
          package = pkgs.codex;

          settings = {
            model = "gpt-6.2-astra";
            personality = "pragmatic";

            approval_policy = "on-request";
            approvals_reviewer = "auto_review";
            sandbox_mode = "workspace-write";

            model_reasoning_effort = "xhigh";
            service_tier = "default";
            model_verbosity = "medium";

            projects."${config.home.homeDirectory}/dev/anwa" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/atollion" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/infra" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/yoseru" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/tegami" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/muketsu" = {
              trust_level = "trusted";
            };

            projects."${config.home.homeDirectory}/dev/heliopause-dominion" = {
              trust_level = "trusted";
            };

            mcp_servers.openaiDeveloperDocs = {
              url = "https://developers.openai.com/mcp";
              startup_timeout_sec = 20;
              tool_timeout_sec = 60;
              default_tools_approval_mode = "auto";
            };

            mcp_servers.terraform = {
              command = lib.getExe terraformMcpServer;
              args = [ "stdio" ];
              startup_timeout_sec = 20;
              tool_timeout_sec = 120;
              default_tools_approval_mode = "prompt";
            };
          };
        };
      }

    )
  ];
}
