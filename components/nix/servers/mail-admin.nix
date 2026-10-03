_: {
  nixos.modules.services-aws-mail-admin =
    { pkgs, ... }:
    let
      vpn = builtins.fromJSON (builtins.readFile ../../../deployments/homelab/cloud/mail-admin-vpn.json);
      direct = builtins.fromJSON (
        builtins.readFile ../../../deployments/homelab/cloud/mail-direct-vpn.json
      );
      directOrigin = "${direct.hostname}:${toString direct.httpsPort}";
      python = pkgs.python3.withPackages (ps: [ ps.boto3 ]);
      acmeState = pkgs.writeShellApplication {
        name = "mail-admin-acme-state";
        text = ''
          exec ${python}/bin/python ${../../cloud/services/mail-aws/acme-state.py} "$@"
        '';
      };
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
          jq --exit-status 'all(.private_key, .preshared_key, .direct_private_key, .direct_preshared_key;
            type == "string" and test("^[A-Za-z0-9+/]{43}=$"))' "$document" >/dev/null
          {
            printf '%s\n' '[Interface]' 'Address = ${vpn.address}' 'MTU = 1420'
            jq --raw-output '"PrivateKey = " + .private_key' "$document"
            printf '%s\n' '[Peer]' 'PublicKey = ${vpn.routerPublicKey}'
            jq --raw-output '"PresharedKey = " + .preshared_key' "$document"
            printf '%s\n' 'Endpoint = ${vpn.endpoint}' 'AllowedIPs = ${vpn.gatewaySource}' 'PersistentKeepalive = 25'
          } > "$candidate"
          install -m 0600 "$candidate" /run/mail-admin-vpn/wg-mail.conf
          {
            printf '%s\n' '[Interface]' 'Address = ${direct.address}' 'MTU = 1420' 'ListenPort = ${toString direct.listenPort}'
            jq --raw-output '"PrivateKey = " + .direct_private_key' "$document"
            printf '%s\n' '[Peer]' 'PublicKey = ${direct.clientPublicKey}'
            jq --raw-output '"PresharedKey = " + .direct_preshared_key' "$document"
            printf '%s\n' 'AllowedIPs = ${direct.clientAddress}'
          } > "$candidate"
          install -m 0600 "$candidate" /run/mail-admin-vpn/wg-mail-admin.conf
          jq --exit-status --join-output '.dns_api_token | select(type == "string" and length >= 20)' \
            "$document" > "$candidate"
          install -m 0600 "$candidate" /run/mail-admin-vpn/dns-api-token
        '';
      };
      proxy = origin: ''
        proxy_set_header Host ${origin};
        proxy_set_header X-Forwarded-For "";
        proxy_set_header X-Real-IP "";
        proxy_set_header Forwarded "";
        proxy_set_header Accept-Encoding "";
        proxy_redirect https://mail.fahrican.com/ https://${origin}/;
        proxy_read_timeout 3600s;
        proxy_buffering off;
      '';
      locations = origin: {
        "/" = {
          proxyPass = "http://127.0.0.1:8081";
          proxyWebsockets = true;
          extraConfig = proxy origin;
        };
        # Rewrite only discovery documents. Mail bodies and JMAP data are intact.
        "~ ^/(api/discover/|[.]well-known/(oauth|openid)|jmap/session$)" = {
          proxyPass = "http://127.0.0.1:8081";
          extraConfig = proxy origin + ''
            sub_filter_types application/json;
            sub_filter_once off;
            sub_filter 'https://mail.fahrican.com/' 'https://${origin}/';
            sub_filter 'wss://mail.fahrican.com/' 'wss://${origin}/';
          '';
        };
      };
      stateService = action: {
        wants = [ "network-online.target" ];
        after = [ "network-online.target" ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${acmeState}/bin/mail-admin-acme-state ${action}";
          EnvironmentFile = "/etc/stalwart-bootstrap/aws.env";
          UMask = "0077";
        };
      };
    in
    {
      networking.wg-quick.interfaces.wg-mail.configFile = "/run/mail-admin-vpn/wg-mail.conf";
      networking.wg-quick.interfaces.wg-mail-admin.configFile = "/run/mail-admin-vpn/wg-mail-admin.conf";
      networking.firewall.allowedUDPPorts = [ direct.listenPort ];
      networking.firewall.interfaces.wg-mail.allowedTCPPorts = [ 8080 ];
      networking.firewall.interfaces.wg-mail-admin.allowedTCPPorts = [ direct.httpsPort ];
      # Keep the two routes independent: nginx may start or reload with either
      # tunnel interface absent. Its sockets remain bound to private IPs only.
      boot.kernel.sysctl."net.ipv4.ip_nonlocal_bind" = 1;
      systemd.services.mail-admin-vpn-secrets = {
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        before = [
          "wg-quick-wg-mail.service"
          "wg-quick-wg-mail-admin.service"
        ];
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
      systemd.services.wg-quick-wg-mail-admin = {
        after = [ "mail-admin-vpn-secrets.service" ];
        requires = [ "mail-admin-vpn-secrets.service" ];
      };
      systemd.services.nginx.after = [
        "wg-quick-wg-mail.service"
        "wg-quick-wg-mail-admin.service"
      ];
      systemd.services.mail-admin-acme-restore = stateService "restore";
      systemd.services.mail-admin-acme-save = stateService "save";
      systemd.services.acme-setup = {
        after = [ "mail-admin-acme-restore.service" ];
        requires = [ "mail-admin-acme-restore.service" ];
      };
      systemd.services."acme-order-renew-${direct.hostname}" = {
        after = [ "mail-admin-vpn-secrets.service" ];
        requires = [ "mail-admin-vpn-secrets.service" ];
      };
      security.acme = {
        acceptTerms = true;
        defaults.email = "fahricanelidemir@gmail.com";
        certs.${direct.hostname} = {
          dnsProvider = "cloudflare";
          dnsResolver = "1.1.1.1:53";
          credentialFiles.CF_DNS_API_TOKEN_FILE = "/run/mail-admin-vpn/dns-api-token";
          group = "nginx";
          reloadServices = [ "nginx.service" ];
          postRun = "${pkgs.systemd}/bin/systemctl start mail-admin-acme-save.service";
        };
      };
      services.nginx = {
        enable = true;
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
          locations = locations "mail-admin.fahrican.com";
        };
        virtualHosts.${direct.hostname} = {
          listen = [
            {
              addr = direct.serverAddress;
              port = direct.httpsPort;
              ssl = true;
            }
          ];
          onlySSL = true;
          useACMEHost = direct.hostname;
          extraConfig = ''
            allow 10.21.92.0/24;
            deny all;
            client_max_body_size 50m;
            add_header Strict-Transport-Security "max-age=31536000" always;
          '';
          locations = locations directOrigin;
        };
      };
    };
}
