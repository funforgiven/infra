_: {
  nixos.modules.audio =
    { pkgs, ... }:
    {
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
        wireplumber.package = pkgs.wireplumber.overrideAttrs (_: rec {
          version = "0.5.15";
          src = pkgs.fetchFromGitLab {
            domain = "gitlab.freedesktop.org";
            owner = "pipewire";
            repo = "wireplumber";
            tag = version;
            hash = "sha256-28JrX8V23VpTe6GPI6g/JlN7412yJLMcwEre2Jv77qg=";
          };
        });
      };
    };
}
