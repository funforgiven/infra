{ inputs, ... }:
{
  imports = [ "${inputs.git-hooks}/flake-module.nix" ];

  flake-file.inputs.git-hooks = {
    url = "github:cachix/git-hooks.nix";
    flake = false;
  };

  perSystem =
    { config, ... }:
    {
      pre-commit.check.enable = false;
      repository.devShell.shellHook = config.pre-commit.installationScript;
    };
}
