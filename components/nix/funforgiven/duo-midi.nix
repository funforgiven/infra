{ config, lib, ... }:
let
  mkPackage =
    {
      pkgs,
      audioctl,
      niri,
    }:
    pkgs.writeShellApplication {
      name = "funforgiven-duo-midi";
      runtimeInputs = [
        audioctl
        niri
        pkgs.pipewire
        pkgs.libnotify
      ];
      text = ''
        exec ${
          pkgs.python3.withPackages (ps: [
            ps.mido
            ps.python-rtmidi
          ])
        }/bin/python3 ${../duo-midi}/pads.py "$@"
      '';
    };
in
{
  home.gui =
    { config, pkgs, ... }:
    let
      package = mkPackage {
        inherit pkgs;
        audioctl = config.dendritic.audioControllerPackage;
        niri = config.programs.niri.package;
      };
    in
    {
      home.packages = [ package ];

      systemd.user.services.funforgiven-duo-midi = {
        Unit = {
          Description = "RØDECaster Duo audio routing and home-control pads";
          After = [
            "graphical-session.target"
            "wireplumber.service"
          ];
          PartOf = [ "graphical-session.target" ];
          Requisite = [ "graphical-session.target" ];
          ConditionEnvironment = "NIRI_SOCKET";
        };
        Service = {
          ExecStart = "${lib.getExe package} listen";
          LoadCredential = [ "ha-webhooks:/run/secrets/home-assistant-midi-webhooks" ];
          Restart = "on-failure";
          RestartSec = 2;
          PassEnvironment = [ "NIRI_SOCKET" ];
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
    let
      home = config.flake.nixosConfigurations.parmigiano.config.home-manager.users.funforgiven;
      package = mkPackage {
        inherit pkgs;
        audioctl = home.dendritic.audioControllerPackage;
        niri = home.programs.niri.package;
      };
    in
    {
      checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
        duo-midi = pkgs.runCommandLocal "duo-midi-check" { } ''
          ${pkgs.python3}/bin/python3 -B ${../duo-midi}/tests.py ${../duo-midi}
          ${lib.getExe package} --help > /dev/null
          ${lib.getExe package} trigger loft-light --dry-run
          ${lib.getExe package} trigger loft-airflow --dry-run
          touch "$out"
        '';
      };
    };
}
