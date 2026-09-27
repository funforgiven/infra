_: {
  home.gui =
    { lib, pkgs, ... }:
    let
      python = pkgs.python3.withPackages (ps: [
        ps.mido
        ps.python-rtmidi
      ]);
      package = pkgs.writeShellApplication {
        name = "funforgiven-home-midi";
        text = ''
          exec ${python}/bin/python3 ${../home-midi/controls.py} "$@"
        '';
      };
    in
    {
      options.dendritic.homeMidiPackage = lib.mkOption {
        type = lib.types.package;
        readOnly = true;
        internal = true;
        description = "Duo MIDI controls for the loft light and AC airflow.";
      };

      config = {
        dendritic.homeMidiPackage = package;
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
    };
}
