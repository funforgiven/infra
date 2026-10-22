{
  config,
  inputs,
  lib,
  ...
}:
let
  user = config.users.funforgiven;
  atollionWorkspace = "${user.homeDirectory}/dev/atollion";
  hostIdentityPath = "/etc/ssh/ssh_host_ed25519_key";
  homelabHosts =
    (builtins.fromJSON (builtins.readFile ../../../deployments/homelab/hosts/inventory.json)).hosts;
  # Verification-only key for older signed commits.
  historicalSigningPublicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHj9lWCKgMOZg6K1QzZvNH0QYY4m0lA0l6A+E4wVdVMT historical-signing-key";
  apiTokensFile = ../../../secrets/api-tokens.yaml;
  githubSshKeyFile = ../../../secrets/github-ssh-key.sops;
  routerosSecretsFile = ../../../secrets/routeros.yaml;
  kubernetesSecretsFile = ../../../secrets/kubernetes.yaml;
  passwordHashesFile = ../../../secrets/password-hashes.yaml;
  passwordHashSecretName = "${user.username}-password-hash";
  apiTokenKeys = {
    atollion-github-cli-token = "codex/atollion_github_cli_token";
    context7-api-key = "codex/context7_api_key";
  };
  consumerSecretNames = builtins.attrNames apiTokenKeys ++ [ "github-ssh-key" ];
  runtimeSecretSpecs = {
    home-assistant-midi-webhooks = {
      key = "home_midi/webhooks";
      sopsFile = ../../../secrets/home-assistant-midi.yaml;
    };
    homelab-routeros-ccr2004-login-password = {
      key = "routeros/ccr2004_login_password";
      sopsFile = routerosSecretsFile;
    };
    homelab-routeros-crs510-login-password = {
      key = "routeros/crs510_login_password";
      sopsFile = routerosSecretsFile;
    };
    homelab-routeros-ccr2004-wireguard-private-key = {
      key = "routeros/ccr2004_wireguard_private_key";
      sopsFile = routerosSecretsFile;
    };
    homelab-routeros-ccr2004-wireguard-parmigiano-preshared-key = {
      key = "routeros/ccr2004_wireguard_parmigiano_preshared_key";
      sopsFile = routerosSecretsFile;
    };
    homelab-routeros-ccr2004-wireguard-mail-preshared-key = {
      key = "preshared_key";
      sopsFile = ../../../secrets/mail-vpn.yaml;
    };
    homelab-routeros-ccr2004-mullvad-private-key = {
      key = "routeros/ccr2004_mullvad_private_key";
      sopsFile = routerosSecretsFile;
    };
    cluster-host-age-identity = {
      key = "cluster/host_age_identity";
      sopsFile = kubernetesSecretsFile;
    };
    cluster-flux-age-identity = {
      key = "cluster/flux_age_identity";
      sopsFile = kubernetesSecretsFile;
    };
  };

  mkSecretMcpLauncher =
    {
      name,
      package,
      pkgs,
      secretPath,
      variable,
    }:
    pkgs.writeShellApplication {
      name = "${name}-with-secret";
      text = ''
        readonly secret_file=${lib.escapeShellArg secretPath}

        if [ ! -r "$secret_file" ]; then
          printf '${name}: required secret is not readable: %s\n' "$secret_file" >&2
          exit 1
        fi

        secret_value="$(< "$secret_file")"
        if [ -z "$secret_value" ]; then
          printf '${name}: required secret is empty: %s\n' "$secret_file" >&2
          exit 1
        fi
        export ${variable}="$secret_value"
        unset secret_value

        exec ${lib.getExe package} "$@"
      '';
    };

  mkSecretConsumers =
    {
      secretPaths,
      sshConfigPath,
    }:
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      allowedSignersFile = "${config.home.homeDirectory}/.ssh/allowed_signers";
      githubPublicKey = user.accounts.github.sshPublicKey;
      mkManagedHostSshSettings =
        {
          hostName,
          username,
        }:
        {
          HostName = hostName;
          User = username;
          IdentityAgent = "none";
          IdentitiesOnly = true;
          IdentityFile = secretPaths.github-ssh-key;
          StrictHostKeyChecking = "yes";
        };
      managedHostSshSettings = lib.mapAttrs (_: mkManagedHostSshSettings) (
        lib.mapAttrs (_: host: {
          hostName = host.management;
          inherit (user) username;
        }) homelabHosts
        // {
          burrata = {
            hostName = "10.21.90.8";
            username = "root";
          };
        }
      );
      context7McpLauncher = mkSecretMcpLauncher {
        name = "context7-mcp";
        package = pkgs.context7-mcp;
        inherit pkgs;
        secretPath = secretPaths.context7-api-key;
        variable = "CONTEXT7_API_KEY";
      };
      atollionGithubCli = pkgs.writeShellApplication {
        name = "gh";
        text = ''
          readonly atollion_repository=funforgiven/atollion
          atollion_workspace="$(${lib.getExe' pkgs.coreutils "realpath"} --canonicalize-missing ${lib.escapeShellArg atollionWorkspace})"
          readonly atollion_workspace

          case "''${1:-}" in
            --help|-h|help|--version|version|completion|__complete*)
              exec ${lib.getExe pkgs.gh} "$@"
              ;;
            auth)
              printf 'gh: authentication commands are disabled for the Atollion-scoped credential.\n' >&2
              exit 1
              ;;
          esac

          session_directory="$(${lib.getExe' pkgs.coreutils "realpath"} --canonicalize-existing .)"
          readonly session_directory
          repository_root="$(${lib.getExe pkgs.git} -C "$session_directory" rev-parse --show-toplevel 2>/dev/null)" || {
            printf 'gh: run this repository-scoped command inside %s.\n' "$atollion_workspace" >&2
            exit 1
          }
          repository_root="$(${lib.getExe' pkgs.coreutils "realpath"} --canonicalize-existing "$repository_root")"
          readonly repository_root

          if [[ "$repository_root" != "$atollion_workspace" ]]; then
            printf 'gh: the managed credential is restricted to %s.\n' "$atollion_workspace" >&2
            exit 1
          fi

          readonly secret_file=${lib.escapeShellArg secretPaths.atollion-github-cli-token}
          if [[ ! -r "$secret_file" ]]; then
            printf 'gh: required Atollion token is not readable: %s\n' "$secret_file" >&2
            exit 1
          fi

          token="$(< "$secret_file")"
          if [[ "$token" != github_pat_* ]]; then
            unset token
            printf 'gh: the Atollion credential must be a configured fine-grained GitHub token.\n' >&2
            exit 1
          fi

          unset GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN GH_DEBUG
          export GH_TOKEN="$token"
          export GH_HOST=github.com
          export GH_REPO="$atollion_repository"
          export GH_PROMPT_DISABLED=1
          unset token

          exec ${lib.getExe pkgs.gh} "$@"
        '';
      };
    in
    {
      config = {
        home.file = {
          ".ssh/config".source = lib.mkForce (config.lib.file.mkOutOfStoreSymlink sshConfigPath);
          ".ssh/allowed_signers".text = ''
            ${config.programs.git.settings.user.email} ${githubPublicKey}
            ${config.programs.git.settings.user.email} ${historicalSigningPublicKey}
          '';
          ".ssh/github_ed25519.pub".text = "${githubPublicKey}\n";
        };

        programs = {
          codex.enableMcpIntegration = true;

          gh.package = atollionGithubCli;

          git = {
            signing = {
              format = "ssh";
              key = secretPaths.github-ssh-key;
              signByDefault = true;
            };
            settings.gpg.ssh.allowedSignersFile = allowedSignersFile;
          };

          mcp = {
            enable = true;
            servers = {
              context7 = {
                command = lib.getExe context7McpLauncher;
                startup_timeout_sec = 20;
                tool_timeout_sec = 60;
                default_tools_approval_mode = "auto";
              };
            };
          };

          ssh = {
            enable = true;
            enableDefaultConfig = false;
            settings = {
              "github.com" = {
                HostName = "github.com";
                User = "git";
                IdentityAgent = "none";
                IdentitiesOnly = true;
                IdentityFile = secretPaths.github-ssh-key;
              };
              "*".IdentityAgent = "none";
            }
            // managedHostSshSettings;
          };
        };
      };
    };
in
{
  perSystem =
    { pkgs, ... }:
    {
      packages = {
        inherit (pkgs) age sops ssh-to-age;
      };
    };

  nixos.modules.funforgiven-secrets.imports = [
    inputs.sops-nix.nixosModules.sops
    (
      { config, lib, ... }:
      let
        deployedSecretPaths = lib.genAttrs consumerSecretNames (name: config.sops.secrets.${name}.path);
        githubSshConfig = config.sops.templates."github-ssh-config";
        secretPermissions = {
          owner = config.users.users.${user.username}.name;
          group = config.users.users.${user.username}.group;
          mode = "0400";
        };
      in
      {
        assertions = [
          {
            assertion = lib.any (key: key.path == hostIdentityPath) config.services.openssh.hostKeys;
            message = "The sops-nix age identity must be declared as an OpenSSH host key.";
          }
        ];

        sops = {
          defaultSopsFile = apiTokensFile;
          defaultSopsFormat = "yaml";
          age.sshKeyPaths = [ hostIdentityPath ];
          secrets =
            lib.mapAttrs (_: key: secretPermissions // { inherit key; }) apiTokenKeys
            // lib.mapAttrs (_: specification: secretPermissions // specification) runtimeSecretSpecs
            // {
              github-ssh-key = secretPermissions // {
                sopsFile = githubSshKeyFile;
                format = "binary";
              };
              "${passwordHashSecretName}" = {
                sopsFile = passwordHashesFile;
                key = "users/${user.username}/password_hash";
                neededForUsers = true;
                mode = "0400";
              };
            };
          templates."github-ssh-config" = secretPermissions // {
            content = config.home-manager.users.${user.username}.home.file.".ssh/config".text;
            mode = "0600";
          };
        };

        home-manager.users.${user.username}.imports = [
          (mkSecretConsumers {
            secretPaths = deployedSecretPaths;
            sshConfigPath = githubSshConfig.path;
          })
        ];

        programs.ssh.systemd-ssh-proxy.enable = false;
        services.openssh.generateHostKeys = true;
        users.users.${user.username}.hashedPasswordFile =
          config.sops.secrets.${passwordHashSecretName}.path;
      }
    )
  ];
}
