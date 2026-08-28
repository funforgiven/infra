{
  config,
  lib,
  ...
}:
let
  expectedChannelIds = [
    "system"
    "game"
    "voice"
    "music"
  ];

  nonEmptySingleLineStr = lib.types.addCheck lib.types.singleLineStr (value: value != "");
  stableId = lib.types.strMatching "[A-Za-z0-9][A-Za-z0-9._-]*";
  unitGain = lib.types.addCheck lib.types.float (gain: gain >= 0.0 && gain <= 1.0);

  channelType = lib.types.submodule {
    options = {
      id = lib.mkOption {
        type = lib.types.enum expectedChannelIds;
        description = "Name used in generated PipeWire and WirePlumber configuration.";
      };

      label = lib.mkOption {
        type = nonEmptySingleLineStr;
        description = "Channel name shown in the mixer.";
      };

      sinkName = lib.mkOption {
        type = stableId;
        description = "PipeWire node.name of the logical sink.";
      };

      bridgeName = lib.mkOption {
        type = stableId;
        description = "PipeWire node.name of the stream that sends this channel to hardware.";
      };

      isDefault = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Route new streams here when WirePlumber has no saved route.";
      };

      initialGain = lib.mkOption {
        type = unitGain;
        description = "Bridge volume used until WirePlumber saves one.";
      };
    };
  };

  identityNormalizationType = lib.types.submodule {
    options = {
      matches = lib.mkOption {
        type = lib.types.listOf (lib.types.attrsOf nonEmptySingleLineStr);
        description = "WirePlumber properties used to recognize an application whose ID changes.";
      };

      persistentId = lib.mkOption {
        type = stableId;
        description = "application.id assigned so WirePlumber can restore the application's route.";
      };
    };
  };

  audioType = lib.types.submodule {
    options = {
      channels = lib.mkOption {
        type = lib.types.listOf channelType;
        default = [ ];
        description = "Logical audio channels in display and routing order.";
      };

      identityNormalizations = lib.mkOption {
        type = lib.types.listOf identityNormalizationType;
        default = [ ];
        description = ''
          Rules that give applications with changing IDs a consistent
          application.id. These rules do not choose a channel.
        '';
      };
    };
  };

  audio = config.dendritic.audio;

  mkAudioctl =
    pkgs: channels:
    let
      renderName = property: channel: ''
        [${lib.escapeShellArg channel.id}]=${lib.escapeShellArg channel.${property}}
      '';
      audioctlSource = lib.removePrefix "#!/usr/bin/env bash\n\n" (
        builtins.readFile ./audio-channels/audioctl.sh
      );
    in
    pkgs.writeShellApplication {
      name = "funforgiven-audioctl";
      runtimeInputs = [
        pkgs.coreutils
        pkgs.jq
        pkgs.pipewire
        pkgs.util-linux
      ];
      text = ''
        declare -Ar expected_sink_names=(
        ${lib.concatMapStringsSep "" (renderName "sinkName") channels}
        )
        declare -Ar expected_bridge_names=(
        ${lib.concatMapStringsSep "" (renderName "bridgeName") channels}
        )

        ${audioctlSource}
      '';
      meta.description = "Move PipeWire streams and logical channels";
    };

  mkChannelPolicy =
    channels:
    let
      renderChannel = channel: ''
        [${builtins.toJSON channel.id}] = {
          sink = ${builtins.toJSON channel.sinkName},
          bridge = ${builtins.toJSON channel.bridgeName},
        },
      '';
    in
    ''
      local channels = {
      ${lib.concatMapStringsSep "" renderChannel channels}
      }

      ${builtins.readFile ./audio-channels/channel-output-policy.lua}
    '';

  audioDataModule = {
    options.dendritic = {
      audio = lib.mkOption {
        type = audioType;
        readOnly = true;
        description = "Audio channel settings used by PipeWire, WirePlumber, and Quickshell.";
      };

      audioControllerPackage = lib.mkOption {
        type = lib.types.package;
        readOnly = true;
        internal = true;
        description = "funforgiven-audioctl configured for these channels.";
      };
    };

    config.dendritic.audio = audio;
  };
in
{
  options.dendritic.audio = lib.mkOption {
    type = audioType;
    default = { };
    description = ''
      Logical playback channels and optional application identity rules.
      WirePlumber stores hardware targets and per-application routes.
    '';
  };

  config = {
    nixos.modules.audio-channels =
      {
        config,
        pkgs,
        ...
      }:
      let
        cfg = config.dendritic.audio;
        inherit (cfg) channels;
        ids = map (channel: channel.id) channels;
        sinkNames = map (channel: channel.sinkName) channels;
        bridgeNames = map (channel: channel.bridgeName) channels;
        defaultChannels = builtins.filter (channel: channel.isDefault) channels;

        unique = values: builtins.length (lib.unique values) == builtins.length values;

        markerProperties = channel: kind: {
          "funforgiven.audio.channel" = channel.id;
          "funforgiven.audio.kind" = kind;
        };

        mkLoopbackModule = channel: {
          name = "libpipewire-module-loopback";
          args = {
            "node.description" = channel.label;
            "audio.position" = [
              "FL"
              "FR"
            ];

            "capture.props" = {
              "node.name" = channel.sinkName;
              "node.description" = channel.label;
              "media.class" = "Audio/Sink";
              "node.virtual" = true;
              "priority.session" = if channel.isDefault then 2000 else 100;
            }
            // markerProperties channel "sink";

            "playback.props" = {
              "node.name" = channel.bridgeName;
              "node.description" = "${channel.label} output";
              "application.id" = channel.bridgeName;
              "node.passive" = true;
              "node.dont-fallback" = true;
              "node.linger" = true;
              "target.object" = "-1";
            }
            // markerProperties channel "bridge";
          };
        };

        loopbackModules = map mkLoopbackModule channels;

        mkBridgeStateRule = channel: {
          matches = [
            {
              "node.name" = channel.bridgeName;
              "funforgiven.audio.channel" = channel.id;
              "funforgiven.audio.kind" = "bridge";
            }
          ];
          actions."update-props" = {
            "state.restore-target" = false;
            "state.default-volume" = channel.initialGain;
          };
        };

        mkIdentityNormalizationRule = normalization: {
          matches = map (
            match:
            match
            // {
              "media.class" = "Stream/Output/Audio";
              "node.name" = "!~^funforgiven\\.audio\\.channel\\..*";
            }
          ) normalization.matches;
          actions."update-props"."application.id" = normalization.persistentId;
        };

        bridgeStateRules = map mkBridgeStateRule channels;
        identityNormalizationRules = map mkIdentityNormalizationRule cfg.identityNormalizations;
        streamRules = bridgeStateRules ++ identityNormalizationRules;
        audioctl = mkAudioctl pkgs channels;
        channelOutputPolicy = mkChannelPolicy channels;
        channelOutputPolicyConfig = pkgs.writeTextDir "share/wireplumber/wireplumber.conf.d/21-funforgiven-channel-output-policy.conf" ''
          wireplumber.components = [
            {
              name = funforgiven/channel-output-policy.lua
              type = script/lua
              provides = custom.funforgiven-channel-output-policy
              requires = [ metadata.default ]
              before = [ support.standard-event-source ]
            }
          ]

          wireplumber.profiles = {
            main = {
              custom.funforgiven-channel-output-policy = required
            }
            policy = {
              custom.funforgiven-channel-output-policy = required
            }
          }
        '';

        wirePlumberSettings = {
          "linking.allow-moving-streams" = true;
          "node.stream.restore-target" = true;
          "node.stream.restore-props" = true;
          "node.restore-default-targets" = false;
        };

        allowedNormalizationMatchProperties = [
          "application.id"
          "application.name"
          "application.process.binary"
          "client.name"
          "media.name"
        ];

        normalizationMatchesAreValid =
          normalization:
          normalization.matches != [ ]
          && lib.all (
            match:
            match != { }
            && lib.all (property: builtins.elem property allowedNormalizationMatchProperties) (
              builtins.attrNames match
            )
          ) normalization.matches;

        normalizationTargetsAreValid = lib.all (
          normalization: !(builtins.elem normalization.persistentId (ids ++ sinkNames ++ bridgeNames))
        ) cfg.identityNormalizations;

        identityRulesOnlySetApplicationId = lib.all (
          rule: builtins.attrNames rule.actions."update-props" == [ "application.id" ]
        ) identityNormalizationRules;

        identityRulesArePlaybackOnly = lib.all (
          rule:
          lib.all (
            match:
            match."media.class" == "Stream/Output/Audio"
            && match."node.name" == "!~^funforgiven\\.audio\\.channel\\..*"
          ) rule.matches
        ) identityNormalizationRules;

        restoreTargetRules = builtins.filter (
          rule: rule.actions."update-props" ? "state.restore-target"
        ) streamRules;

        restoreTargetRulesAreBridgeOnly =
          builtins.length restoreTargetRules == builtins.length channels
          && lib.all (
            rule:
            rule.actions."update-props"."state.restore-target" == false
            && builtins.length rule.matches == 1
            && (builtins.head rule.matches)."funforgiven.audio.kind" == "bridge"
            && builtins.elem (builtins.head rule.matches)."node.name" bridgeNames
          ) restoreTargetRules;

        containsUnsafeDeclarativeTarget =
          value:
          if builtins.isAttrs value then
            lib.any (
              name:
              name == "node.target"
              || (name == "target.object" && value.${name} != "-1")
              || containsUnsafeDeclarativeTarget value.${name}
            ) (builtins.attrNames value)
          else if builtins.isList value then
            lib.any containsUnsafeDeclarativeTarget value
          else
            false;
      in
      {
        imports = [ audioDataModule ];

        assertions = [
          {
            assertion = config.services.pipewire.enable;
            message = "The audio-channels feature requires the base PipeWire audio feature.";
          }
          {
            assertion = config.services.pipewire.wireplumber.enable;
            message = "The audio-channels feature requires WirePlumber.";
          }
          {
            assertion = builtins.length channels == 4;
            message = "dendritic.audio.channels must contain exactly four channels.";
          }
          {
            assertion = ids == expectedChannelIds;
            message = "Audio channel IDs and order must be: system, game, voice, music.";
          }
          {
            assertion = unique ids;
            message = "Every audio channel ID must be unique.";
          }
          {
            assertion = unique sinkNames;
            message = "Every logical audio sink node name must be unique.";
          }
          {
            assertion = unique bridgeNames;
            message = "Every audio bridge node name must be unique.";
          }
          {
            assertion = unique (sinkNames ++ bridgeNames);
            message = "Logical sink and bridge node names must not collide.";
          }
          {
            assertion = builtins.length defaultChannels == 1;
            message = "Exactly one logical audio channel must be marked as default.";
          }
          {
            assertion = map (channel: channel.id) defaultChannels == [ "system" ];
            message = "System must be the only default audio channel.";
          }
          {
            assertion = lib.all normalizationMatchesAreValid cfg.identityNormalizations;
            message = ''
              Audio identity rules need at least one match and may use only
              stable stream properties.
            '';
          }
          {
            assertion =
              normalizationTargetsAreValid && identityRulesOnlySetApplicationId && identityRulesArePlaybackOnly;
            message = ''
              Audio identity rules may change only application.id on playback
              streams outside the channel graph. They cannot reuse a channel,
              sink, or bridge ID.
            '';
          }
          {
            assertion = restoreTargetRulesAreBridgeOnly;
            message = ''
              Only the four bridge rules may disable state.restore-target.
              Application stream restore must stay enabled.
            '';
          }
          {
            assertion =
              builtins.attrNames wirePlumberSettings == [
                "linking.allow-moving-streams"
                "node.restore-default-targets"
                "node.stream.restore-props"
                "node.stream.restore-target"
              ];
            message = "The audio policy must declare exactly the four required WirePlumber settings.";
          }
          {
            assertion =
              !(containsUnsafeDeclarativeTarget loopbackModules)
              && lib.all (module: module.args."playback.props"."target.object" == "-1") loopbackModules;
            message = ''
              Audio loopbacks may set target.object only to -1. WirePlumber
              chooses physical outputs at runtime.
            '';
          }
        ];

        environment.systemPackages = [ audioctl ];

        dendritic.audioControllerPackage = audioctl;

        services.pipewire = {
          extraConfig.pipewire."20-funforgiven-audio-channels" = {
            "context.modules" = loopbackModules;
          };

          wireplumber = {
            extraScripts."funforgiven/channel-output-policy.lua" = channelOutputPolicy;
            configPackages = [ channelOutputPolicyConfig ];

            extraConfig."20-funforgiven-audio-channels" = {
              "wireplumber.settings" = wirePlumberSettings;
              "stream.rules" = streamRules;
            };
          };
        };
      };

    home.gui =
      { config, pkgs, ... }:
      let
        audioctl = mkAudioctl pkgs config.dendritic.audio.channels;
      in
      {
        imports = [ audioDataModule ];
        dendritic.audioControllerPackage = audioctl;
        home.packages = [ audioctl ];
      };
  };
}
