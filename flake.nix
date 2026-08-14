{
  description = "Homelab NixOS, network, and private-cloud infrastructure";

  outputs = inputs: import ./outputs.nix inputs;

  nixConfig = {
    abort-on-warn = true;
    warn-dirty = false;
  };

  inputs = {
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    files = {
      url = "github:mightyiam/files";
      flake = false;
    };
    flake-file.url = "github:denful/flake-file";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      flake = false;
    };
    hermes-agent = {
      url = "git+https://github.com/NousResearch/hermes-agent.git?rev=f80f453ae0679347e38abc917c7f94f717bf96c5&shallow=1";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    import-tree.url = "github:vic/import-tree";
    mcp-nixos = {
      url = "github:utensils/mcp-nixos";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    niri = {
      url = "github:sodiboo/niri-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nixos-anywhere = {
      url = "git+https://github.com/nix-community/nixos-anywhere.git?rev=bad98b0685cf47eaeadcaf6787da8b51cf025693&shallow=1";
      inputs = {
        disko.follows = "disko";
        nixpkgs.follows = "nixpkgs";
      };
    };
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    stylix = {
      url = "github:nix-community/stylix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    wallpaper = {
      url = "path:/home/funforgiven/Pictures/Wallpapers/current.png";
      flake = false;
    };
  };
}
