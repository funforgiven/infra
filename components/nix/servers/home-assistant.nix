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
      };

      services.home-assistant = {
        enable = true;
        extraComponents = [
          "backup"
          "default_config"
          "esphome"
          "met"
          "mobile_app"
          "mqtt"
          "radio_browser"
        ];
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
          http = {
            server_host = [
              "0.0.0.0"
              "::"
            ];
            trusted_proxies = [ "192.168.80.0/24" ];
            use_x_forwarded_for = true;
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
