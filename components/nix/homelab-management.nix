_:
let
  homelabHostKeys = builtins.fromJSON (
    builtins.readFile ../../deployments/homelab/ssh-host-keys.json
  );
in
{
  dendritic.nixpkgs.allowUnfreePackages = [ "winbox" ];

  nixos.modules.homelab-management = { pkgs, ... }: {
    # Ansible and interactive OpenSSH both use the standard global trust file.
    programs.ssh.knownHosts = builtins.mapAttrs (_: hostKey: {
      inherit (hostKey) hostNames publicKey;
    }) homelabHostKeys;

    programs.winbox = {
      enable = true;
      # Reuse the installed 4.3 package while MikroTik's download is unreachable.
      # Remove this package override once the upstream 4.4 download is available.
      package =
        let
          previousNixpkgs = fetchTree {
            type = "github";
            owner = "NixOS";
            repo = "nixpkgs";
            rev = "2fcb964de67fcf60b43471c55d5d99e61a9ccb5a";
            narHash = "sha256-RzPPiWeUtuvymnpuEWsdtzli5w4kjZs49FqEs3/1u+I=";
          };
          previousPackages = import previousNixpkgs.outPath {
            inherit (pkgs.stdenv.hostPlatform) system;
            config.allowUnfreePredicate = package: pkgs.lib.getName package == "winbox";
          };
        in
        previousPackages.winbox4;
    };

    # Kubespray's pinned Ansible runtime is isolated in its upstream container.
    virtualisation.podman.enable = true;
  };
}
