{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    let
      secretScan = pkgs.writeShellApplication {
        name = "repository-secret-scan";
        runtimeInputs = [
          pkgs.gitMinimal
          pkgs.gitleaks
        ];
        text = ''
          set -euo pipefail

          repository_root="$(git rev-parse --show-toplevel)"
          readonly repository_root

          gitleaks dir \
            --no-banner \
            --redact \
            "$repository_root"

          gitleaks git \
            --no-banner \
            --redact \
            "$repository_root"
        '';
      };
    in
    {
      packages.repository-secret-scan = secretScan;

      pre-commit.settings.hooks.gitleaks = {
        enable = true;
        name = "gitleaks staged secret scan";
        description = "Reject staged plaintext secrets with redacted output";
        entry = "${pkgs.gitleaks}/bin/gitleaks git --staged --no-banner --redact";
        pass_filenames = false;
        stages = [ "pre-commit" ];
      };

      checks.repository-secret-scan =
        pkgs.runCommandLocal "repository-secret-scan"
          {
            nativeBuildInputs = [ pkgs.gitleaks ];
          }
          ''
            gitleaks dir \
              --no-banner \
              --redact \
              ${inputs.self}
            touch "$out"
          '';
    };
}
