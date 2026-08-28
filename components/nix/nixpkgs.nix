{
  config,
  inputs,
  lib,
  ...
}:
let
  cfg = config.dendritic.nixpkgs;

  mkPkgs =
    system:
    import inputs.nixpkgs {
      inherit system;
      config = cfg.effectiveConfig;
      overlays = [ config.flake.overlays.default ];
    };
in
{
  options.dendritic.nixpkgs = {
    config = lib.mkOption {
      type = lib.types.attrs;
      default = { };
      description = "nixpkgs settings applied to every package set and host.";
    };

    allowUnfreePackages = lib.mkOption {
      type = lib.types.listOf lib.types.singleLineStr;
      default = [ ];
      description = "Unfree package names permitted by this repository.";
    };

    effectiveConfig = lib.mkOption {
      type = lib.types.attrs;
      readOnly = true;
      description = "Final nixpkgs settings, including the unfree-package allowlist.";
    };

    overlays = lib.mkOption {
      type = lib.types.listOf lib.types.unspecified;
      default = [ ];
      description = "Overlays applied to every package set and host.";
    };
  };

  config = {
    dendritic.nixpkgs.effectiveConfig = cfg.config // {
      allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) cfg.allowUnfreePackages;
    };

    flake = {
      lib.mkPkgs = mkPkgs;
      overlays.default = lib.composeManyExtensions cfg.overlays;
    };

    perSystem =
      { system, ... }:
      let
        pkgs = mkPkgs system;
      in
      {
        _module.args.pkgs = pkgs;
        legacyPackages = pkgs;
      };
  };
}
