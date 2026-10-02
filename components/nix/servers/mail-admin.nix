_: {
  nixos.modules.services-aws-mail-admin =
    { pkgs, ... }:
    let
      vpn = builtins.fromJSON (builtins.readFile ../../../deployments/homelab/cloud/mail-admin-vpn.json);
      syncVpn = pkgs.writeShellApplication {
        name = "sync-mail-admin-vpn";
        runtimeInputs = [
          pkgs.awscli2
          pkgs.coreutils
          pkgs.jq
        ];
        text = ''
          set -euo pipefail
          umask 077
          install -d -m 0700 /run/mail-admin-vpn
          document="$(mktemp /run/mail-admin-vpn/secret.XXXXXX)"
          candidate="$(mktemp /run/mail-admin-vpn/config.XXXXXX)"
          trap 'rm -f "$document" "$candidate"' EXIT
          aws --region eu-central-1 secretsmanager get-secret-value \
            --secret-id fahrican/stalwart/vpn --query SecretString --output text > "$document"
          jq --exit-status 'all(.private_key, .preshared_key; type == "string" and test("^[A-Za-z0-9+/]{43}=$"))' \
            "$document" >/dev/null
          {
            printf '%s\n' '[Interface]' 'Address = ${vpn.address}' 'MTU = 1420'
            jq --raw-output '"PrivateKey = " + .private_key' "$document"
            printf '%s\n' '[Peer]' 'PublicKey = ${vpn.routerPublicKey}'
            jq --raw-output '"PresharedKey = " + .preshared_key' "$document"
            printf '%s\n' 'Endpoint = ${vpn.endpoint}' 'AllowedIPs = ${vpn.gatewaySource}' 'PersistentKeepalive = 25'
          } > "$candidate"
          install -m 0600 "$candidate" /run/mail-admin-vpn/wg-mail.conf
        '';
      };
      proxy = ''
        proxy_set_header Host mail-admin.fahrican.com;
        proxy_set_header X-Forwarded-For "";
        proxy_set_header Forwarded "";
        proxy_set_header Accept-Encoding "";
        proxy_redirect https://mail.fahrican.com/ https://mail-admin.fahrican.com/;
        proxy_read_timeout 3600s;
        proxy_buffering off;
      '';
    in
    {
      # Only the services gateway's SNAT address can use this backend. The
      # gateway separately admits administrator devices from wg-admin only.
      networking.wg-quick.interfaces.wg-mail.configFile = "/run/mail-admin-vpn/wg-mail.conf";
      networking.firewall.interfaces.wg-mail.allowedTCPPorts = [ 8080 ];
      systemd.services.mail-admin-vpn-secrets = {
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        before = [ "wg-quick-wg-mail.service" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${syncVpn}/bin/sync-mail-admin-vpn";
          UMask = "0077";
        };
      };
      systemd.services.wg-quick-wg-mail = {
        after = [ "mail-admin-vpn-secrets.service" ];
        requires = [ "mail-admin-vpn-secrets.service" ];
      };
      systemd.services.nginx = {
        after = [ "wg-quick-wg-mail.service" ];
        requires = [ "wg-quick-wg-mail.service" ];
      };
      services.nginx = {
        enable = true;
        # Do not create public listeners or log OAuth capability URLs.
        appendHttpConfig = "access_log off;";
        virtualHosts."mail-admin.fahrican.com" = {
          listen = [
            {
              addr = vpn.backendAddress;
              port = 8080;
            }
          ];
          extraConfig = ''
            allow ${vpn.gatewaySource};
            deny all;
            client_max_body_size 50m;
          '';
          locations."/" = {
            proxyPass = "http://127.0.0.1:8081";
            proxyWebsockets = true;
            extraConfig = proxy;
          };
          # Stalwart publishes one global origin. Rewrite discovery documents
          # only, so private UI login and JMAP never send admin tokens publicly.
          locations."~ ^/(api/discover/|[.]well-known/(oauth|openid)|jmap/session$)" = {
            proxyPass = "http://127.0.0.1:8081";
            extraConfig = proxy + ''
              sub_filter_types application/json;
              sub_filter_once off;
              sub_filter 'https://mail.fahrican.com' 'https://mail-admin.fahrican.com';
              sub_filter 'wss://mail.fahrican.com' 'wss://mail-admin.fahrican.com';
            '';
          };
        };
      };
    };
}
