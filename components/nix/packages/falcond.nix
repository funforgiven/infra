_: {
  perSystem =
    { pkgs, ... }:
    {
      packages = {
        inherit (pkgs) falcond;
      };
    };

  dendritic.nixpkgs.overlays = [
    (final: _prev: {
      falcond = final.callPackage (
        {
          lib,
          stdenv,
          fetchFromGitHub,
          runCommand,
          zig_0_16,
        }:

        let
          pname = "falcond";
          version = "2.0.14";
          src = fetchFromGitHub {
            owner = "PikaOS-Linux";
            repo = "falcond";
            rev = "09639985ffd781b34f540074b04292abb24f4d32";
            hash = "sha256-EQrJSfP+kAmgtXILYTW+jZl4jOudSmEj39uDB5ycrew=";
          };
          zigDeps =
            runCommand "${pname}-${version}-zig-deps"
              {
                src = "${src}/falcond";
                nativeBuildInputs = [ zig_0_16 ];
                outputHashAlgo = null;
                outputHashMode = "recursive";
                outputHash = "sha256-ghj+f4AOB8YEhBXkXmCq2JnIjEKT91Cr5Qar7qeIU5Q=";
              }
              ''
                export ZIG_GLOBAL_CACHE_DIR="$(mktemp -d)"
                mkdir -p "$ZIG_GLOBAL_CACHE_DIR/tmp"

                runHook unpackPhase
                cd "$sourceRoot"

                pipewire_manifest="$PWD/zig-pkg/otter_desktop-0.11.25-nwUfzR_gMAAgl_0gKsnjpPiOOkEfVxTP8eL4_3kow8uQ/vendor/pipewire/build.zig.zon"
                if ! zig build --fetch; then
                  test -f "$pipewire_manifest"
                fi
                substituteInPlace "$pipewire_manifest" \
                  --replace-fail \
                  "https://github.com/allyourcodebase/valgrind.h/archive/refs/tags/3.23.0.tar.gz" \
                  "https://codeload.github.com/allyourcodebase/valgrind.h/tar.gz/refs/tags/3.23.0"
                zig build --fetch

                mv "$ZIG_GLOBAL_CACHE_DIR/p" "$out"
              '';
        in
        stdenv.mkDerivation rec {
          inherit
            pname
            version
            src
            zigDeps
            ;

          sourceRoot = "${src.name}/falcond";

          nativeBuildInputs = [ zig_0_16.hook ];

          postConfigure = ''
            ln -s ${zigDeps} "$ZIG_GLOBAL_CACHE_DIR/p"
          '';

          zigBuildFlags = [
            "-Dconfig-path=/etc/falcond/config.conf"
            "-Dprofiles-dir=/etc/falcond/profiles"
            "-Duser-profiles-dir=/var/empty/falcond"
            "-Dsystem-conf-path=/var/empty/falcond-system.conf"
          ];

          zigCheckFlags = zigBuildFlags;

          doCheck = true;

          meta = {
            description = "Automatic Linux gaming performance daemon";
            homepage = "https://github.com/PikaOS-Linux/falcond";
            license = lib.licenses.mit;
            mainProgram = "falcond";
            platforms = lib.platforms.linux;
          };
        }
      ) { };
    })
  ];
}
