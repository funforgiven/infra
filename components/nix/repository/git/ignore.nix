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
      "/.envrc"
      "__pycache__/"
      "*.py[cod]"
      "/hardware-configuration.nix"
      "/result"
      "/result-*"
      "*.backup"
      "before-infra-*.rsc"
      "/secrets/*.hash"
      "/secrets/*.key"
      "/secrets/*.pem"
    ];

    perSystem.files.file.".gitignore".text = lib.concatLines cfg;
  };
}
