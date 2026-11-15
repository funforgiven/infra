{ lib, ... }:
{
  perSystem =
    { pkgs, ... }:
    {
      packages =
        lib.optionalAttrs (lib.meta.availableOn pkgs.stdenv.hostPlatform pkgs.proton-cachyos-bin)
          {
            inherit (pkgs) proton-cachyos-bin;
          };
    };

  dendritic.nixpkgs.overlays = [
    (final: _prev: {
      proton-cachyos-bin = final.callPackage (
        {
          lib,
          stdenvNoCC,
          fetchzip,
        }:
        stdenvNoCC.mkDerivation (finalAttrs: {
          pname = "proton-cachyos-bin";
          version = "11.0-20261015";
          steamDisplayName = "Proton-CachyOS";

          # The SLR build runs inside UMU's Steam Linux Runtime on NixOS.
          # Use the baseline x86_64 variant rather than requiring x86_64-v3.
          src = fetchzip {
            url = "https://github.com/CachyOS/proton-cachyos/releases/download/cachyos-${finalAttrs.version}-slr/proton-cachyos-${finalAttrs.version}-slr-x86_64.tar.xz";
            hash = "sha256-Vb1AvDQLIpgxr3ABPMstM3DFRN1tfUD+6OnhQirMnAQ=";
          };

          dontUnpack = true;
          dontConfigure = true;
          dontBuild = true;

          outputs = [
            "out"
            "steamcompattool"
          ];

          installPhase = ''
            runHook preInstall

            echo "Use proton-cachyos-bin.steamcompattool with UMU or programs.steam.extraCompatPackages." > "$out"
            mkdir "$steamcompattool"
            ln -s "$src"/* "$steamcompattool"/
            rm "$steamcompattool/compatibilitytool.vdf"
            cp "$src/compatibilitytool.vdf" "$steamcompattool/"
            substituteInPlace "$steamcompattool/compatibilitytool.vdf" \
              --replace-fail "proton-cachyos-${finalAttrs.version}-slr-x86_64" "${finalAttrs.steamDisplayName}"

            runHook postInstall
          '';

          doInstallCheck = true;
          installCheckPhase = ''
            runHook preInstallCheck
            test -x "$steamcompattool/proton"
            test -x "$steamcompattool/files/bin/wine"
            test -x "$steamcompattool/files/bin/wineserver"
            test -s "$steamcompattool/toolmanifest.vdf"
            test -s "$steamcompattool/compatibilitytool.vdf"
            runHook postInstallCheck
          '';

          meta = {
            description = "Proton with CachyOS patches for Steam and UMU";
            homepage = "https://github.com/CachyOS/proton-cachyos";
            license = lib.licenses.bsd3;
            platforms = [ "x86_64-linux" ];
            sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
          };
        })
      ) { };
    })
  ];
}
