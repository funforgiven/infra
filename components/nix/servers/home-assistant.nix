_: {
  nixos.modules.services-home-assistant =
    {
      config,
      ...
    }:
    {
      # Neutron's external provider subnet deliberately has no DHCP. Match the
      # declaratively assigned port MAC while retaining DHCP on the private
      # services interface.
      networking.useNetworkd = true;

      systemd.network.networks."10-home-assistant-provider" = {
        matchConfig.MACAddress = "fa:16:3e:80:00:10";
        address = [ "10.21.40.120/24" ];
        networkConfig.LinkLocalAddressing = "no";
        routes = [
          {
            Destination = "10.21.10.0/24";
            Gateway = "10.21.40.1";
          }
        ];
      };

      services.home-assistant = {
        enable = true;
        extraComponents = [
          "backup"
          "default_config"
          "esphome"
          "google_translate"
          "met"
          "mobile_app"
          "mqtt"
          "radio_browser"
        ];
        # Home Assistant 2026.8 migrated HTTP settings into its authenticated
        # runtime store. The narrow UI exception and recovery procedure are
        # recorded in deployments/homelab/cloud/manual-exceptions.yaml.
        config = {
          default_config = { };
          homeassistant = {
            country = "TR";
            currency = "TRY";
            external_url = "https://home.fahrican.com";
            internal_url = "http://192.168.80.10:8123";
            name = "Home";
            time_zone = "Europe/Istanbul";
            unit_system = "metric";
          };
        };
      };

      servicesPlatform.backup = {
        paths = [ "/var/lib/hass" ];
        tag = "home-assistant-state";
      };

      servicesPlatform.alerting.units = [
        "home-assistant"
        "restic-backups-service-state"
      ];

      networking.firewall.allowedTCPPorts = [ 8123 ];

      assertions = [
        {
          assertion = config.systemd.network.enable;
          message = "Home Assistant's static provider address requires systemd-networkd.";
        }
      ];
    };
}
