_:
let
  mkServer = cloudFeature: serviceFeature: {
    system = "x86_64-linux";
    stateVersion = "26.05";
    user = "funforgiven";
    homeProfiles = [ ];
    features = [
      "services-server-common"
      "services-host-backup"
      "services-host-monitoring"
      cloudFeature
      serviceFeature
    ];
  };
in
{
  dendritic.hosts = {
    hermes = mkServer "services-openstack-guest" "services-hermes";
    home-assistant = mkServer "services-openstack-guest" "services-home-assistant";
    mail-edge = mkServer "services-hetzner-guest" "services-mail-edge";
  };
}
