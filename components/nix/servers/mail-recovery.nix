_: {
  perSystem =
    { pkgs, ... }:
    {
      packages.mail-restore-drill = pkgs.writeShellApplication {
        name = "mail-restore-drill";
        runtimeInputs = [
          pkgs.stalwart-cli
          pkgs.stalwart-vandelay
        ];
        text = ''
          exec ${pkgs.python3}/bin/python ${../../cloud/services/mail-aws/restore-drill.py} "$@"
        '';
      };
    };
}
