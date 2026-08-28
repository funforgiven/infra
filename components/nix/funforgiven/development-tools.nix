_: {
  dendritic.nixpkgs.allowUnfreePackages = [ "terraform" ];

  home.base =
    { pkgs, ... }:
    {
      home.packages = [
        pkgs.awscli2
        pkgs.fd
        pkgs.nodejs
        pkgs.python312
        pkgs.ripgrep
        pkgs.terraform
        pkgs.uv
      ];
    };
}
