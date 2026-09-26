_: {
  home.gui =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    let
      python = pkgs.python3.withPackages (ps: [
        ps.mido
        ps.python-rtmidi
      ]);
      package = pkgs.writeShellApplication {
        name = "funforgiven-audio-midi";
        runtimeInputs = [
          config.dendritic.audioControllerPackage
          config.programs.niri.package
          pkgs.pipewire
          pkgs.libnotify
        ];
        text = ''
          exec ${python}/bin/python3 ${../audio-channels/midi-router.py} "$@"
        '';
      };
    in
    {
      options.dendritic.audioMidiPackage = lib.mkOption {
        type = lib.types.package;
        readOnly = true;
        internal = true;
        description = "Duo MIDI controls for routing the focused application's audio.";
      };

      config = {
        dendritic.audioMidiPackage = package;
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
    };
}
