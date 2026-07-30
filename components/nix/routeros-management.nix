_: {
  dendritic.nixpkgs.allowUnfreePackages = [ "winbox" ];

  nixos.modules.routeros-management = {
    programs.winbox = {
      enable = true;
      openFirewall = true;
    };
  };
}
