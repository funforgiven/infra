{ inputs, ... }:
{
  nixos.modules.services-aws-guest =
    { lib, ... }:
    {
      imports = [
        (inputs.nixpkgs + "/nixos/modules/virtualisation/amazon-image.nix")
      ];

      services.amazon-ssm-agent.enable = true;

      # Session Manager is the administration plane. The SSH daemon remains a
      # local recovery tool but receives no AWS security-group ingress rule, and
      # amazon-image's key-based root login is turned off.
      services.openssh.settings.PermitRootLogin = lib.mkForce "no";
    };
}
