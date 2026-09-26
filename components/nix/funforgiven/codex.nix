_: {
  dendritic.nixpkgs.allowUnfreePackages = [ "terraform" ];

  home.base.imports = [
    (
      {
        config,
        lib,
        pkgs,
        ...
      }:
      let
        codexVersion = "0.153.3";
        python = pkgs.python312;
        codexPackage = pkgs.codex.overrideAttrs (
          finalAttrs: _: {
            version = codexVersion;
            src = pkgs.fetchFromGitHub {
              owner = "openai";
              repo = "codex";
              tag = "rust-v${finalAttrs.version}";
              hash = "sha256-JujjJx9GHcTgirqEFr9tc4Ghzx65YNOqpNCc7rtthfI=";
            };
            cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
              inherit (finalAttrs)
                pname
                version
                src
                sourceRoot
                ;
              hash = "sha256-GG6kOXmCdq+bZLU2ul0DIVL8lDuweayvZvXn6+bcUZw=";
            };
          }
        );
        terraformMcpServer = pkgs.terraform-mcp-server;
      in
      {
        assertions = [
          {
            assertion = codexPackage.version == codexVersion;
            message = "The Codex package must provide the pinned ${codexVersion} release.";
          }
        ];

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
          package = codexPackage;

          settings = {
            model = "gpt-6-astra";
            personality = "pragmatic";

            approval_policy = "on-request";
            approvals_reviewer = "auto_review";
            sandbox_mode = "workspace-write";

            model_reasoning_effort = "xhigh";
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
