_: {
  perSystem =
    { pkgs, ... }:
    {
      packages.instawow = pkgs.instawow;
    };

  dendritic.nixpkgs.overlays = [
    (final: prev: {
      # Nixpkgs' 7.0.0.post1 predates Forever. Backport upstream's flavour
      # support and product detection without pulling in another flake.
      instawow = prev.instawow.overridePythonAttrs (old: {
        patches = (old.patches or [ ]) ++ [
          (final.fetchurl {
            url = "https://github.com/layday/instawow/commit/311f161fe98f46273029bde5ea66a7170e9937f9.patch";
            hash = "sha256-lXTfd3J13Lw6Unlr8ke9vI1E31RbiPX2bXg0HiQ8BLw=";
          })
          (final.fetchurl {
            url = "https://github.com/layday/instawow/commit/1976d31de839aac6eef2ee42bd69a25c723eb722.patch";
            hash = "sha256-43fe6UOg6k1Xeu2hlRk9+ZYpE/M6z+wXFg1P7q8zeFo=";
          })
        ];
      });
    })
  ];
}
