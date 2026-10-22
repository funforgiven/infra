{ config, lib, ... }:
{
  nixos.modules.obsbot-tiny3 = {
    services.pipewire.wireplumber.extraConfig."31-obsbot-privacy" = {
      "monitor.alsa.rules" = [
        {
          matches = [
            {
              "device.vendor.id" = "0x3564";
              "device.product.id" = "0xff02";
            }
          ];
          actions."update-props"."device.disabled" = true;
        }
      ];
    };
  };

  home.gui =
    { lib, pkgs, ... }:
    let
      controller = pkgs.writeShellApplication {
        name = "obsbot-control";
        runtimeInputs = [ pkgs.python3 ];
        text = ''
          export PYTHONDONTWRITEBYTECODE=1
          exec python3 ${./obsbot}/controller.py "$@"
        '';
      };
    in
    {
      options.dendritic.cameraControllerPackage = lib.mkOption {
        type = lib.types.package;
        readOnly = true;
        description = "OBSBOT Tiny 3 UVC controller for Quickshell.";
      };
      config = {
        dendritic.cameraControllerPackage = controller;
        home.packages = [ controller ];
      };
    };

  perSystem =
    { pkgs, system, ... }:
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        obsbot-controller = pkgs.runCommandLocal "obsbot-controller-tests" { } ''
          export PYTHONDONTWRITEBYTECODE=1
          ${pkgs.python3}/bin/python3 -m unittest discover -s ${./obsbot} -v
          touch "$out"
        '';
      };
    };
}
