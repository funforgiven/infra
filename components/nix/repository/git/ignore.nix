{ config, lib, ... }:
let
  cfg = config.git.ignore;
in
{
  options.git.ignore = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [ ];
    apply = lib.naturalSort;
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
      "/deployments/homelab/cloud/**/admin.conf"
      "/deployments/homelab/cloud/**/kubeconfig"
      "/deployments/homelab/cloud/**/*.agekey"
      "*.backup"
      "before-infra-*.rsc"
      "/secrets/*.hash"
      "/secrets/*.key"
      "/secrets/*.pem"
    ];

    perSystem.files.file.".gitignore".text = lib.concatLines cfg;
  };
}
