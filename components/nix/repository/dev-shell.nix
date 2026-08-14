_: {
  perSystem =
    {
      config,
      lib,
      pkgs,
      ...
    }:
    {
      options.repository.devShell.shellHook = lib.mkOption {
        type = lib.types.lines;
        default = "";
      };

      config = {
        devShells.default = pkgs.mkShellNoCC {
          packages = [
            config.files.writer.drv
            config.treefmt.build.wrapper
            pkgs.age
            pkgs.gitMinimal
            pkgs.gitleaks
            pkgs.kubectl
            pkgs.kustomize
            pkgs.nixd
            (pkgs.python3.withPackages (pythonPackages: [
              pythonPackages.ansible
              pythonPackages.ansible-core
              pythonPackages.pyyaml
              pythonPackages.requests
            ]))
            pkgs.ripgrep
            pkgs.shellcheck
            pkgs.xorriso
            pkgs.yamllint
          ];

          shellHook = config.repository.devShell.shellHook;
        };
      };
    };
}
