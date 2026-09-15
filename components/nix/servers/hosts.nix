_: {
  dendritic.hosts = {
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
