{ config, lib, ... }:
let
  cfg = config.git.ignore;
in
{
  options.git.ignore = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [ ];
    apply = lib.naturalSort;
    description = "Patterns written to the generated .gitignore file.";
  };

  config = {
    git.ignore = [
      "/.codex-doc-cache/"
      "/.direnv/"
      ".env"
      ".env.*"
      "**/.terraform/"
      "*.tfstate"
      "*.tfstate.*"
      "*.tfvars"
      "*.tfvars.json"
      "/.envrc"
      "__pycache__/"
      "*.py[cod]"
      "/hardware-configuration.nix"
      "/result"
      "/result-*"
      "/deployments/homelab/**/admin.conf"
      "/deployments/homelab/**/kubeconfig"
      "/deployments/homelab/**/*.agekey"
      "*.backup"
      "before-infra-*.rsc"
      "/secrets/*.hash"
      "/secrets/*.key"
      "/secrets/*.pem"
      "/secrets/mail-aws-vpn.conf"
      "secrets/home-assistant-token.local"
    ];

    perSystem.files.file.".gitignore".text = lib.concatLines cfg;
  };
}
