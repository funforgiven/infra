{ lib, ... }:
{
  dendritic.nixpkgs.allowUnfreePackages = [ "hayase" ];

  perSystem =
    { pkgs, ... }:
    {
      packages = lib.optionalAttrs (lib.meta.availableOn pkgs.stdenv.hostPlatform pkgs.hayase) {
        inherit (pkgs) hayase;
      };
    };

  dendritic.nixpkgs.overlays = [
    (final: _prev: {
      hayase = final.callPackage (
        {
          lib,
          stdenv,
          fetchurl,
          dpkg,
          autoPatchelfHook,
          addDriverRunpath,
          asar,
          makeWrapper,
          alsa-lib,
          at-spi2-core,
          cairo,
          cups,
          dbus,
          expat,
          glib,
          gtk3,
          libappindicator-gtk3,
          libdrm,
          libgbm,
          libglvnd,
          libnotify,
          libsecret,
          libuuid,
          libx11,
          libxcb,
          libxcomposite,
          libxdamage,
          libxext,
          libxfixes,
          libxrandr,
          libxscrnsaver,
          libxtst,
          libxkbcommon,
          nspr,
          nss,
          pango,
          systemd,
          wayland,
          xdg-utils,
        }:

        let
          version = "6.4.86";
          runtimeLibs = [
            alsa-lib
            at-spi2-core
            cairo
            cups
            dbus
            expat
            glib
            gtk3
            libappindicator-gtk3
            libdrm
            libgbm
            libglvnd
            libnotify
            libsecret
            libuuid
            libxkbcommon
            nspr
            nss
            pango
            systemd
            wayland
            libx11
            libxcb
            libxcomposite
            libxdamage
            libxext
            libxfixes
            libxrandr
            libxscrnsaver
            libxtst
          ];
        in
        stdenv.mkDerivation {
          pname = "hayase";
          inherit version;

          src = fetchurl {
            url = "https://api.hayase.watch/files/linux-hayase-${version}-linux.deb";
            hash = "sha256-95/PQcGsAZ5txJj0rsvjmvPZuK7zRoIZ9QGLfZZi8Co=";
          };

          nativeBuildInputs = [
            autoPatchelfHook
            asar
            dpkg
            makeWrapper
          ];

          buildInputs = runtimeLibs;

          unpackPhase = ''
            runHook preUnpack
            dpkg-deb -x "$src" .
            runHook postUnpack
          '';

          installPhase = ''
            runHook preInstall

            mkdir -p "$out/bin" "$out/opt/Hayase" "$out/share"
            cp -r opt/Hayase/* "$out/opt/Hayase/"
            cp -r usr/share/applications usr/share/icons "$out/share/"

            asar extract "$out/opt/Hayase/resources/app.asar" hayase-app
            substituteInPlace hayase-app/out/main/index.js \
              --replace-fail \
                'require("./bytecode-loader.cjs");' \
                'const { app } = require("electron"); app.on("browser-window-created", (_event, window) => { if (window.getTitle() === "Hayase") window.show(); }); require("./bytecode-loader.cjs");'
            asar pack hayase-app "$out/opt/Hayase/resources/app.asar"

            substituteInPlace "$out/share/applications/hayase.desktop" \
              --replace-fail "/opt/Hayase/hayase" "$out/bin/hayase"

            makeWrapper "$out/opt/Hayase/hayase" "$out/bin/hayase" \
              --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath runtimeLibs}:$out/opt/Hayase:${addDriverRunpath.driverLink}/lib" \
              --prefix PATH : "${lib.makeBinPath [ xdg-utils ]}" \
              --suffix VK_ADD_DRIVER_FILES : "${addDriverRunpath.driverLink}/share/vulkan/icd.d" \
              --add-flags "\''${NIXOS_OZONE_WL:+\''${WAYLAND_DISPLAY:+--ozone-platform=wayland --enable-features=WaylandWindowDecorations --disable-features=Vulkan}}"

            runHook postInstall
          '';

          dontStrip = true;

          meta = {
            description = "Torrent streaming made simple";
            homepage = "https://hayase.watch";
            license = lib.licenses.unfree;
            mainProgram = "hayase";
            platforms = [ "x86_64-linux" ];
            sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
          };
        }
      ) { };
    })
  ];
}
