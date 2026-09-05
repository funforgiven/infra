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
    home-assistant = mkServer "services-openstack-guest" "services-home-assistant";
    gitlab = mkServer "services-openstack-guest" "services-gitlab";
    mail-aws = {
      system = "aarch64-linux";
      stateVersion = "26.05";
      user = "funforgiven";
      homeProfiles = [ ];
      features = [
        "services-server-common"
        "services-aws-guest"
        "services-aws-mail"
      ];
    };
  };
}
