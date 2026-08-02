_:
let
  homelabHostKeys = builtins.fromJSON (
    builtins.readFile ../../deployments/homelab/ssh-host-keys.json
  );
in
{
  dendritic.nixpkgs.allowUnfreePackages = [ "winbox" ];

  nixos.modules.homelab-management = {
    # Ansible and interactive OpenSSH both use the standard global trust file.
    programs.ssh.knownHosts = builtins.mapAttrs (_: hostKey: {
      inherit (hostKey) hostNames publicKey;
    }) homelabHostKeys;

    programs.winbox = {
      enable = true;
    };

    # Kubespray's pinned Ansible runtime is isolated in its upstream container.
    virtualisation.podman.enable = true;
  };
}
