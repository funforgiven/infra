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
          exec ${pkgs.python3}/bin/python ${../../homelab/services/mail-aws/restore-drill.py} "$@"
        '';
      };
    };
}
