_:
let
  # USB 1 exposes PCM 0 (Main) and PCM 1 (Chat) on the same ALSA card.
  usbId = "USB19f7:0050";

  expandedUsbId = "~USB19f7:00(73|79|95)";

  endpointRule = components: profile: label: {
    matches = [
      {
        "alsa.components" = components;
        "device.profile.name" = profile;
      }
    ];
    actions."update-props" = {
      "node.description" = "RØDECaster Duo ${label}";
      "node.nick" = "RØDECaster Duo ${label}";
    };
  };
in
{
  nixos.modules.rodecaster-duo =
    { pkgs, ... }:
    let
      # UCM's native SplitPCM support creates device-backed stereo outputs.
      # Keep the distribution's profiles and add only the Duo's expanded IDs.
      ucm = pkgs.runCommandLocal "alsa-ucm-rodecaster-duo" { } ''
        mkdir -p "$out"
        cp -rs ${pkgs.alsa-ucm-conf}/share "$out/share"
        ucm_dir="$out/share/alsa/ucm2/USB-Audio"
        chmod u+w "$ucm_dir" "$ucm_dir/RODE"
        mkdir -p "$ucm_dir/conf.d" "$ucm_dir/RODE"
        install -m 0444 ${./rodecaster-duo/Expanded.conf} \
          "$ucm_dir/RODE/RODECaster-Duo-Expanded.conf"

        # Expanded playback with old multitrack, stereo, or new multitrack capture.
        for mode in 0073:16 0079:2 0095:20; do
          pid="''${mode%:*}"
          channels="''${mode#*:}"
          cat > "$ucm_dir/conf.d/19f7-$pid.conf" <<EOF
        Define.ProfileName "RODE/RODECaster-Duo-Expanded"
        Define.DuoCaptureChannels $channels
        EOF
        done
      '';
    in
    {
      system.build.rodecaster-duo-ucm = ucm;
      systemd.user.services.wireplumber.environment.ALSA_CONFIG_UCM2 = "${ucm}/share/alsa/ucm2";

      services.pipewire.wireplumber.extraConfig."30-rodecaster-duo" = {
        "monitor.alsa.rules" = [
          {
            matches = [
              {
                "device.name" = "~alsa_card.*";
                "device.vendor.id" = "0x19f7";
                "device.product.id" = "0x0050";
              }
            ];
            actions."update-props" = {
              # Generic stereo profiles expose only Main. Pro Audio creates both
              # Main and Chat sinks/sources, including multitrack when enabled.
              "api.alsa.use-acp" = true;
              "api.alsa.use-ucm" = false;
              "device.profile" = "pro-audio";
            };
          }
          (endpointRule usbId "pro-output-0" "USB 1 Main")
          (endpointRule usbId "pro-output-1" "USB 1 Chat")
          (endpointRule usbId "pro-input-0" "USB 1 Main Capture")
          (endpointRule usbId "pro-input-1" "USB 1 Chat Capture")
          {
            matches = [
              {
                "alsa.components" = usbId;
                "audio.channels" = "2";
              }
            ];
            # Pro Audio normally uses AUX positions. Give stereo applications
            # left/right ports without truncating a multitrack Main capture.
            actions."update-props"."audio.position" = [
              "FL"
              "FR"
            ];
          }
          {
            matches = [
              {
                "device.name" = "~alsa_card.*";
                "device.vendor.id" = "0x19f7";
                "device.product.id" = "~0x00(73|79|95)";
              }
            ];
            actions."update-props" = {
              "api.alsa.use-acp" = true;
              "api.alsa.use-ucm" = true;
              "api.alsa.split-enable" = true;
              "device.profile" = "HiFi";
            };
          }
          (endpointRule expandedUsbId "HiFi: Speaker: sink" "System")
          (endpointRule expandedUsbId "HiFi: Line1: sink" "Game")
          (endpointRule expandedUsbId "HiFi: Line3: sink" "Chat")
          (endpointRule expandedUsbId "HiFi: Line2: sink" "Music")
          (endpointRule expandedUsbId "HiFi: Mic: source" "Chat Capture")
          (endpointRule expandedUsbId "HiFi: Line4: source" "Main Capture")
        ];
      };
    };
}
