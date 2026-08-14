_: {
  nixos.modules.services-mail-edge =
    { config, pkgs, ... }:
    let
      certificateDirectory = config.security.acme.certs."mail.fahrican.com".directory;
      secretDirectory = "/var/lib/stalwart-bootstrap";
    in
    {
      security.acme = {
        acceptTerms = true;
        defaults.email = "fahricanelidemir@gmail.com";
        certs."mail.fahrican.com" = {
          group = "stalwart";
          listenHTTP = ":80";
          reloadServices = [ "stalwart.service" ];
        };
      };

      services.stalwart = {
        enable = true;
        package = pkgs.stalwart_0_15;
        stateVersion = "26.05";
        openFirewall = true;
        credentials = {
          admin-secret = "${secretDirectory}/admin-secret";
          resend-api-key = "${secretDirectory}/resend-api-key";
          tls-certificate = "${certificateDirectory}/fullchain.pem";
          tls-private-key = "${certificateDirectory}/key.pem";
        };
        settings = {
          server = {
            hostname = "mail.fahrican.com";
            listener = {
              smtp = {
                bind = [ "[::]:25" ];
                protocol = "smtp";
              };
              submission = {
                bind = [ "[::]:587" ];
                protocol = "smtp";
              };
              submissions = {
                bind = [ "[::]:465" ];
                protocol = "smtp";
                tls.implicit = true;
              };
              imaptls = {
                bind = [ "[::]:993" ];
                protocol = "imap";
                tls.implicit = true;
              };
              https = {
                bind = [ "[::]:443" ];
                protocol = "http";
                tls.implicit = true;
              };
            };
          };

          certificate.default = {
            cert = "%{file:/run/credentials/stalwart.service/tls-certificate}%";
            private-key = "%{file:/run/credentials/stalwart.service/tls-private-key}%";
          };

          authentication.fallback-admin = {
            user = "admin";
            secret = "%{file:/run/credentials/stalwart.service/admin-secret}%";
          };

          queue = {
            strategy.route = [
              {
                "if" = "is_local_domain('', rcpt_domain)";
                "then" = "'local'";
              }
              { "else" = "'resend'"; }
            ];
            route.resend = {
              type = "relay";
              address = "smtp.resend.com";
              port = 587;
              protocol = "smtp";
              auth = {
                username = "resend";
                secret = "%{file:/run/credentials/stalwart.service/resend-api-key}%";
              };
              tls = {
                implicit = false;
                allow-invalid-certs = false;
              };
            };
          };
        };
      };

      systemd.services.stalwart = {
        after = [ "acme-mail.fahrican.com.service" ];
        wants = [ "acme-mail.fahrican.com.service" ];
        unitConfig.ConditionPathExists = [
          "${secretDirectory}/admin-secret"
          "${secretDirectory}/resend-api-key"
        ];
      };

      systemd.tmpfiles.rules = [
        "d ${secretDirectory} 0700 root root - -"
      ];

      servicesPlatform.backup = {
        paths = [
          "/var/lib/stalwart"
          "/var/lib/acme/mail.fahrican.com"
        ];
        tag = "mail-edge-state";
      };

      servicesPlatform.alerting.units = [
        "acme-mail.fahrican.com"
        "restic-backups-service-state"
        "stalwart"
      ];

      networking.firewall.allowedTCPPorts = [
        25
        80
        443
        465
        587
        993
      ];
    };
}
