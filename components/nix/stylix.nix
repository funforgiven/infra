{
  config,
  inputs,
  lib,
  ...
}:
let
  cfg = config.dendritic.stylix;
in
{
  options.dendritic.stylix.commonModule = lib.mkOption {
    type = lib.types.deferredModule;
    default = { };
    description = "Stylix settings shared by NixOS and Home Manager.";
  };

  config = {
    nixos.modules.stylix.imports = [
      inputs.stylix.nixosModules.stylix
      cfg.commonModule
    ];

    homeManager.standaloneModules.stylix.imports = [
      inputs.stylix.homeModules.stylix
    ];

    home.gui.imports = [ cfg.commonModule ];
  };
}
