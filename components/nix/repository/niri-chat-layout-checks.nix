{ config, lib, ... }:
{
  perSystem =
    { pkgs, system, ... }:
    let
      source = ../funforgiven/window-manager/niri;
    in
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        niri-chat-layout = pkgs.runCommandLocal "niri-chat-layout-check" { } ''
          ${lib.getExe pkgs.python3} ${source}/tests/chat-layout.test.py ${source}/chat-layout.py
          touch "$out"
        '';
      };
    };
}
