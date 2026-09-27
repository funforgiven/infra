{ config, lib, ... }:
{
  perSystem =
    { pkgs, system, ... }:
    let
      host = config.dendritic.hosts.parmigiano;
      username = config.users.${host.user}.username;
      home = config.flake.homeConfigurations."${username}@parmigiano".config;
    in
    {
      checks = lib.mkIf (system == host.system) {
        home-midi = pkgs.runCommandLocal "home-midi-check" { } ''
          ${pkgs.python3}/bin/python3 ${../home-midi/tests.py} ${../home-midi/controls.py}
          ${lib.getExe home.dendritic.homeMidiPackage} trigger loft-light --dry-run
          ${lib.getExe home.dendritic.homeMidiPackage} trigger loft-airflow --dry-run
          touch "$out"
        '';
        audio-midi = pkgs.runCommandLocal "audio-midi-check" { } ''
          ${pkgs.python3}/bin/python3 ${../audio-channels/tests/midi-router.test.py} \
            ${../audio-channels/midi-router.py}
          ${lib.getExe home.dendritic.audioMidiPackage} --help > /dev/null
          touch "$out"
        '';
      };
    };
}
