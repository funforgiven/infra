_: {
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
}
