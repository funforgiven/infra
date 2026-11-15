_: {
  perSystem =
    { pkgs, ... }:
    let
      enroll = pkgs.writeShellApplication {
        name = "enroll-wow-addon-credentials";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.sops
        ];
        text = ''
          exec ${pkgs.python3}/bin/python3 ${./battle-net/enroll_credentials.py} "$@"
        '';
      };
    in
    {
      packages.enroll-wow-addon-credentials = enroll;
      apps.enroll-wow-addon-credentials = {
        program = "${enroll}/bin/enroll-wow-addon-credentials";
        meta.description = "Enroll WoW addon API credentials into workstation SOPS storage";
      };
    };
}
