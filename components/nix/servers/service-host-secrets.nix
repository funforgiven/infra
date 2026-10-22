_: {
  perSystem =
    { pkgs, ... }:
    let
      # Pushes UniFi guest credentials over SSH until the guest consumes SOPS directly.
      enrollServiceHostSecrets = pkgs.writeShellApplication {
        name = "enroll-service-host-secrets";
        runtimeInputs = [
          pkgs.coreutils
          pkgs.gitMinimal
          pkgs.openssh
          pkgs.sops
        ];
        text = builtins.readFile ./enroll-service-host-secrets.sh;
      };
    in
    {
      apps.enroll-service-host-secrets = {
        program = "${enrollServiceHostSecrets}/bin/enroll-service-host-secrets";
        meta.description = "Install a credential profile on a service host";
      };
      packages.enroll-service-host-secrets = enrollServiceHostSecrets;
      # writeShellApplication runs shellcheck while building.
      checks.enroll-service-host-secrets = enrollServiceHostSecrets;
    };
}
