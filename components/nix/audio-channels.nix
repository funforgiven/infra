{ config, lib, ... }:
let
  # Expanded-mode SplitPCM outputs of this RØDECaster Duo (see audio-channels/README.md).
  duo = "alsa_output.usb-R__DE_RODECaster_Duo_IR0076094-00.HiFi__";

  channel =
    {
      id,
      label,
      output,
      isDefault ? false,
    }:
    {
      inherit
        id
        label
        output
        isDefault
        ;
      sinkName = "funforgiven.audio.channel.${id}";
      bridgeName = "funforgiven.audio.channel.${id}.output";
      initialGain = 1.0;
    };

  channels = [
    (channel {
      id = "system";
      label = "System";
      output = "${duo}Speaker__sink";
      isDefault = true;
    })
    (channel {
      id = "game";
      label = "Game";
      output = "${duo}Line1__sink";
    })
    (channel {
      id = "voice";
      label = "Voice Chat";
      output = "${duo}Line3__sink";
    })
    (channel {
      id = "music";
      label = "Music";
      output = "${duo}Line2__sink";
    })
  ];

  mkAudioctl =
    pkgs:
    pkgs.writeShellApplication {
      name = "funforgiven-audioctl";
      runtimeInputs = [
        pkgs.jq
        pkgs.pipewire
      ];
      text = ''
        declare -Ar sink_names=(${
          lib.concatMapStringsSep " " (c: "[${c.id}]=${lib.escapeShellArg c.sinkName}") channels
        })
        ${builtins.readFile ./audio-channels/audioctl.sh}
      '';
      meta.description = "Move a PipeWire playback stream to a logical audio channel";
    };

  # Each channel is a virtual sink whose loopback "bridge" plays into one fixed
  # hardware output. dont-fallback + linger keep a bridge unlinked (instead of
  # falling back to another device, which could create a feedback cycle) while
  # its output is absent; WirePlumber links it again when the output returns.
  loopbackModule = c: {
    name = "libpipewire-module-loopback";
    args = {
      "node.description" = c.label;
      "audio.position" = [
        "FL"
        "FR"
      ];
      "capture.props" = {
        "node.name" = c.sinkName;
        "node.description" = c.label;
        "media.class" = "Audio/Sink";
        "node.virtual" = true;
        "priority.session" = if c.isDefault then 2000 else 100;
        "funforgiven.audio.channel" = c.id;
        "funforgiven.audio.kind" = "sink";
      };
      "playback.props" = {
        "node.name" = c.bridgeName;
        "node.description" = "${c.label} output";
        "application.id" = c.bridgeName;
        "node.passive" = true;
        "node.dont-fallback" = true;
        "node.linger" = true;
        "target.object" = c.output;
        "funforgiven.audio.channel" = c.id;
        "funforgiven.audio.kind" = "bridge";
      };
    };
  };
in
{
  options.dendritic.audio.channels = lib.mkOption {
    type = lib.types.listOf lib.types.attrs;
    readOnly = true;
    default = channels;
    description = "Logical playback channels in display order, shared with Quickshell.";
  };

  config = {
    nixos.modules.audio-channels = {
      services.pipewire = {
        extraConfig.pipewire."20-funforgiven-audio-channels"."context.modules" =
          map loopbackModule channels;

        # A saved per-application target must not override a bridge's fixed output.
        wireplumber.extraConfig."20-funforgiven-audio-channels"."stream.rules" = map (c: {
          matches = [ { "node.name" = c.bridgeName; } ];
          actions.update-props."state.restore-target" = false;
        }) channels;
      };
    };

    home.gui =
      { lib, pkgs, ... }:
      {
        options.dendritic.audioControllerPackage = lib.mkOption {
          type = lib.types.package;
          readOnly = true;
          internal = true;
          description = "funforgiven-audioctl, used by Quickshell and the MIDI router.";
        };

        config = {
          dendritic.audioControllerPackage = mkAudioctl pkgs;
          home.packages = [ (mkAudioctl pkgs) ];
        };
      };

    perSystem =
      { pkgs, system, ... }:
      let
        hostConfig = config.flake.nixosConfigurations.parmigiano.config;
        inherit (hostConfig.services.pipewire) wireplumber;
        audioctl = mkAudioctl pkgs;
      in
      {
        checks = lib.mkIf (system == config.dendritic.hosts.parmigiano.system) {
          audio-channels =
            pkgs.runCommandLocal "funforgiven-audio-channels-check"
              {
                nativeBuildInputs = [
                  audioctl
                  hostConfig.services.pipewire.package
                  wireplumber.package
                  pkgs.jq
                  pkgs.shellcheck
                ];
                PIPEWIRE_SHARE = "${hostConfig.services.pipewire.package}/share/pipewire";
                PIPEWIRE_CONFIG = "${hostConfig.environment.etc.pipewire.source}/pipewire.conf.d";
                WIREPLUMBER_DATA_DIRS = hostConfig.systemd.user.services.wireplumber.environment.XDG_DATA_DIRS;
                CHANNELS = builtins.toJSON channels;
              }
              ''
                shellcheck ${./audio-channels/tests/integration.sh}
                bash ${./audio-channels/tests/integration.sh}
                touch "$out"
              '';
        };
      };
  };
}
