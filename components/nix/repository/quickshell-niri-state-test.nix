{ config, lib, ... }:
let
  hostSystem = config.dendritic.hosts.parmigiano.system;
in
{
  perSystem =
    { pkgs, system, ... }:
    let
      quickshellSource = ../funforgiven/window-manager/quickshell;
    in
    {
      checks = lib.mkIf (system == hostSystem) {
        quickshell-niri-state =
          pkgs.runCommand "quickshell-niri-state-test"
            {
              nativeBuildInputs = [ pkgs.nodejs ];
            }
            ''
              node --test ${quickshellSource}/tests/*.test.js
              touch "$out"
            '';
      };
    };
}
