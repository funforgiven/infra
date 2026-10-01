{ inputs, ... }:
{
  perSystem = { pkgs, system, ... }: {
    packages.disko = inputs.disko.packages.${system}.disko.override {
      # Upstream still uses the deprecated stdenv.isDarwin accessor.
      stdenv = pkgs.stdenv // {
        inherit (pkgs.stdenv.hostPlatform) isDarwin;
      };
    };
  };
}
