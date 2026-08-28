{ inputs, ... }:
{
  imports = [ "${inputs.files}/flake-module.nix" ];

  perSystem = { config, ... }: {
    treefmt.settings.excludes = builtins.attrNames config.files.file;
    files.writer.app = true;
  };
}
