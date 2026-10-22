{ config, lib, ... }:
let
  mkPackage =
    pkgs:
    pkgs.writeShellApplication {
      name = "funforgiven-home-midi";
      text = ''
        exec ${
          pkgs.python3.withPackages (ps: [
            ps.mido
            ps.python-rtmidi
          ])
        }/bin/python3 ${../home-midi/controls.py} "$@"
      '';
    };
in
{
  home.gui =
    { pkgs, ... }:
    let
      package = mkPackage pkgs;
    in
    {
      home.packages = [ package ];
      systemd.user.services.funforgiven-home-midi = {
        Unit = {
          Description = "RØDECaster Duo loft light and AC controls";
          After = [ "graphical-session.target" ];
          PartOf = [ "graphical-session.target" ];
          Requisite = [ "graphical-session.target" ];
        };
        Service = {
          ExecStart = "${lib.getExe package} listen";
          LoadCredential = [ "ha-webhooks:/run/secrets/home-assistant-midi-webhooks" ];
          Restart = "on-failure";
          RestartSec = 2;
          NoNewPrivileges = true;
          RestrictSUIDSGID = true;
          Slice = "session-graphical.slice";
          UMask = "0077";
        };
        Install.WantedBy = [ "graphical-session.target" ];
      };
    };

  perSystem =
    { pkgs, system, ... }:
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        home-midi = pkgs.runCommandLocal "home-midi-check" { } ''
          ${pkgs.python3}/bin/python3 ${../home-midi/tests.py} ${../home-midi/controls.py}
          ${lib.getExe (mkPackage pkgs)} trigger loft-light --dry-run
          ${lib.getExe (mkPackage pkgs)} trigger loft-airflow --dry-run
          touch "$out"
        '';
      };
    };
}
