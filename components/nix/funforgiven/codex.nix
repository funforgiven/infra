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
        awsRegion = "eu-central-1";
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
        uvx = lib.getExe' pkgs.uv "uvx";
        uvEnvironment = {
          UV_NO_MANAGED_PYTHON = "true";
          UV_PYTHON = "${python}/bin/python3";
          UV_PYTHON_DOWNLOADS = "never";
        };
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

            mcp_servers.aws = {
              command = uvx;
              args = [ "awslabs.aws-api-mcp-server==1.3.46" ];
              startup_timeout_sec = 60;
              tool_timeout_sec = 120;
              default_tools_approval_mode = "prompt";
              env = uvEnvironment // {
                AWS_DEFAULT_REGION = awsRegion;
                AWS_REGION = awsRegion;
                FASTMCP_LOG_LEVEL = "ERROR";
                READ_OPERATIONS_ONLY = "true";
              };
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
