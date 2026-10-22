{ config, lib, ... }:
let
  mkPackage =
    {
      pkgs,
      audioctl,
      niri,
    }:
    pkgs.writeShellApplication {
      name = "funforgiven-audio-midi";
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
        }/bin/python3 ${../audio-channels/midi-router.py} "$@"
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

      systemd.user.services.funforgiven-audio-midi = {
        Unit = {
          Description = "RØDECaster Duo focused-application audio routing";
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
          Restart = "on-failure";
          RestartSec = 2;
          PassEnvironment = [ "NIRI_SOCKET" ];
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
        audio-midi = pkgs.runCommandLocal "audio-midi-check" { } ''
          ${pkgs.python3}/bin/python3 ${../audio-channels/tests/midi-router.test.py} \
            ${../audio-channels/midi-router.py}
          ${lib.getExe package} --help > /dev/null
          touch "$out"
        '';
      };
    };
}
