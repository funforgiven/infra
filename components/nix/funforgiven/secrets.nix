{
  config,
  inputs,
  lib,
  ...
}:
let
  user = config.users.funforgiven;
  anwaWorkspace = "${user.homeDirectory}/dev/anwa";
  hostIdentityPath = "/etc/ssh/ssh_host_ed25519_key";
  # Verification-only: existing commits were signed by this public key before
  # the SOPS migration. Keeping it does not invoke or depend on 1Password.
  historicalSigningPublicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHj9lWCKgMOZg6K1QzZvNH0QYY4m0lA0l6A+E4wVdVMT historical-signing-key";
  apiTokensFile = ../../../secrets/api-tokens.yaml;
  githubSshKeyFile = ../../../secrets/github-ssh-key.sops;
  routerosSecretsFile = ../../../secrets/routeros.yaml;
  cloudHostSecretsFile = ../../../secrets/cloud-hosts.yaml;
  kubernetesSecretsFile = ../../../secrets/kubernetes.yaml;
  passwordHashesFile = ../../../secrets/password-hashes.yaml;
  passwordHashSecretName = "${user.username}-password-hash";
  apiTokenKeys = {
    anwa-github-mcp-token = "codex/anwa_github_mcp_token";
    context7-api-key = "codex/context7_api_key";
    github-mcp-token = "codex/github_mcp_token";
  };
  consumerSecretNames = builtins.attrNames apiTokenKeys ++ [ "github-ssh-key" ];
  runtimeSecretSpecs = {
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
    homelab-routeros-ccr2004-mullvad-private-key = {
      key = "routeros/ccr2004_mullvad_private_key";
      sopsFile = routerosSecretsFile;
    };
    cloud-host-taleggio-ubuntu-console-password = {
      key = "cloud_hosts/taleggio/ubuntu_console_password";
      sopsFile = cloudHostSecretsFile;
    };
    cloud-host-asiago-ubuntu-console-password = {
      key = "cloud_hosts/asiago/ubuntu_console_password";
      sopsFile = cloudHostSecretsFile;
    };
    cloud-host-pecorino-ubuntu-console-password = {
      key = "cloud_hosts/pecorino/ubuntu_console_password";
      sopsFile = cloudHostSecretsFile;
    };
    undercloud-kube-encrypt-token = {
      key = "undercloud/kube_encrypt_token";
      sopsFile = kubernetesSecretsFile;
    };
    undercloud-flux-age-identity = {
      key = "undercloud/flux_age_identity";
      sopsFile = kubernetesSecretsFile;
    };
    management-k3s-token = {
      key = "management/k3s_token";
      sopsFile = kubernetesSecretsFile;
    };
    management-flux-age-identity = {
      key = "management/flux_age_identity";
      sopsFile = kubernetesSecretsFile;
    };
  };
  runtimeSecretNames = builtins.attrNames runtimeSecretSpecs;

  mkConsumerSopsSecrets =
    permissions:
    lib.mapAttrs (_: key: permissions // { inherit key; }) apiTokenKeys
    // {
      github-ssh-key = permissions // {
        sopsFile = githubSshKeyFile;
        format = "binary";
      };
    };

  mkRuntimeSopsSecrets =
    permissions: lib.mapAttrs (_: specification: permissions // specification) runtimeSecretSpecs;

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
          user,
        }:
        {
          HostName = hostName;
          User = user;
          IdentityAgent = "none";
          IdentitiesOnly = true;
          IdentityFile = secretPaths.github-ssh-key;
          StrictHostKeyChecking = "yes";
        };
      managedHostSshSettings = lib.mapAttrs (_: mkManagedHostSshSettings) {
        asiago = {
          hostName = "10.21.20.12";
          user = "ubuntu";
        };
        hermes = {
          hostName = "10.21.40.121";
          user = "funforgiven";
        };
        home-assistant = {
          hostName = "10.21.40.120";
          user = "funforgiven";
        };
        pecorino = {
          hostName = "10.21.20.10";
          user = "ubuntu";
        };
        taleggio = {
          hostName = "10.21.20.11";
          user = "ubuntu";
        };
      };
      context7McpLauncher = mkSecretMcpLauncher {
        name = "context7-mcp";
        package = pkgs.context7-mcp;
        inherit pkgs;
        secretPath = secretPaths.context7-api-key;
        variable = "CONTEXT7_API_KEY";
      };
      githubMcpLauncher = mkSecretMcpLauncher {
        name = "github-mcp-server";
        package = pkgs.github-mcp-server;
        inherit pkgs;
        secretPath = secretPaths.github-mcp-token;
        variable = "GITHUB_PERSONAL_ACCESS_TOKEN";
      };
      anwaGithubMcpLauncher = mkSecretMcpLauncher {
        name = "github-mcp-server-anwa";
        package = pkgs.github-mcp-server;
        inherit pkgs;
        secretPath = secretPaths.anwa-github-mcp-token;
        variable = "GITHUB_PERSONAL_ACCESS_TOKEN";
      };
      scopedGithubMcpLauncher = pkgs.writeShellApplication {
        name = "github-mcp-server-scoped";
        text = ''
          anwa_workspace="$(${lib.getExe' pkgs.coreutils "realpath"} --canonicalize-missing ${lib.escapeShellArg anwaWorkspace})"
          readonly anwa_workspace
          session_directory="$(${lib.getExe' pkgs.coreutils "realpath"} --canonicalize-existing .)"
          readonly session_directory

          if [[ "$session_directory" == "$anwa_workspace" || "$session_directory" == "$anwa_workspace/"* ]]; then
            exec ${lib.getExe anwaGithubMcpLauncher} "$@"
          fi

          exec ${lib.getExe githubMcpLauncher} --read-only "$@"
        '';
      };
    in
    {
      options.dendritic.gitAuthenticationPublicKey = lib.mkOption {
        type = lib.types.singleLineStr;
        readOnly = true;
        internal = true;
        description = "Evaluated public identity for Git authentication and signing evidence.";
      };

      config = {
        dendritic.gitAuthenticationPublicKey = githubPublicKey;

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
              github = {
                command = lib.getExe scopedGithubMcpLauncher;
                args = [
                  "--toolsets"
                  "repos,issues,pull_requests,users"
                  "stdio"
                ];
                startup_timeout_sec = 20;
                tool_timeout_sec = 120;
                default_tools_approval_mode = "writes";
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
        passwordHashSecret = config.sops.secrets.${passwordHashSecretName};
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
          {
            assertion =
              passwordHashSecret.neededForUsers
              && passwordHashSecret.path == "/run/secrets-for-users/${passwordHashSecretName}"
              && passwordHashSecret.key == "users/${user.username}/password_hash"
              && passwordHashSecret.mode == "0400"
              && passwordHashSecret.uid == 0
              && passwordHashSecret.gid == 0;
            message = "The account password hash must be an early, root-owned sops-nix user secret.";
          }
          {
            assertion = config.users.users.${user.username}.hashedPasswordFile == passwordHashSecret.path;
            message = "The immutable account must consume the sops-nix password-hash secret.";
          }
          {
            assertion =
              githubSshConfig.owner == secretPermissions.owner
              && githubSshConfig.group == secretPermissions.group
              && githubSshConfig.mode == "0600";
            message = "The OpenSSH client config must be rendered as a private user-owned file.";
          }
          {
            assertion = lib.all (
              name:
              let
                secret = config.sops.secrets.${name};
                specification = runtimeSecretSpecs.${name};
              in
              secret.owner == secretPermissions.owner
              && secret.group == secretPermissions.group
              && secret.mode == secretPermissions.mode
              && secret.path == "/run/secrets/${name}"
              && secret.sopsFile == specification.sopsFile
              && secret.key == specification.key
            ) runtimeSecretNames;
            message = "Runtime infrastructure secrets must be private user-owned files with their declared SOPS source and key.";
          }
        ];

        sops = {
          defaultSopsFile = apiTokensFile;
          defaultSopsFormat = "yaml";
          age.sshKeyPaths = [ hostIdentityPath ];
          secrets =
            mkConsumerSopsSecrets secretPermissions
            // mkRuntimeSopsSecrets secretPermissions
            // {
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

  homeManager.standaloneModules.funforgiven-secrets.imports = [
    inputs.sops-nix.homeManagerModules.sops
    (
      { config, lib, ... }:
      let
        deployedSecretPaths = lib.genAttrs consumerSecretNames (name: config.sops.secrets.${name}.path);
        githubSshConfig = config.sops.templates."github-ssh-config";
      in
      {
        imports = [
          (mkSecretConsumers {
            secretPaths = deployedSecretPaths;
            sshConfigPath = githubSshConfig.path;
          })
        ];

        sops = {
          age.keyFile = "${config.xdg.configHome}/sops/age/keys.txt";
          defaultSopsFile = apiTokensFile;
          defaultSopsFormat = "yaml";
          secrets = mkConsumerSopsSecrets { mode = "0400"; };
          templates."github-ssh-config" = {
            content = config.home.file.".ssh/config".text;
            mode = "0600";
          };
        };
      }
    )
  ];
}
