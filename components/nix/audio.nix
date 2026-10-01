_: {
  nixos.modules.audio = { pkgs, ... }: {
    security.rtkit.enable = true;

    services.pipewire = {
      enable = true;
      alsa = {
        enable = true;
        support32Bit = true;
      };
      pulse.enable = true;
      jack.enable = true;

      # WirePlumber 0.5.18 deadlocks while creating the Duo's SplitPCM
      # loopbacks, blocking discovery of every output and microphone. Keep
      # the last working version until upstream fixes that startup regression.
      wireplumber.package =
        let
          previousNixpkgs = fetchTree {
            type = "github";
            owner = "NixOS";
            repo = "nixpkgs";
            rev = "2fcb964de67fcf60b43471c55d5d99e61a9ccb5a";
            narHash = "sha256-RzPPiWeUtuvymnpuEWsdtzli5w4kjZs49FqEs3/1u+I=";
          };
          previousPackages = import previousNixpkgs.outPath {
            inherit (pkgs.stdenv.hostPlatform) system;
          };
        in
        previousPackages.wireplumber;
    };
  };
}
