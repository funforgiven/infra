_: {
  nixos.modules.services-aws-mail =
    {
      config,
      pkgs,
      ...
    }:
    let
      stateDirectory = "/var/lib/stalwart";
      runtimeDirectory = "/run/stalwart-secrets";
      deploymentEnvironment = "/etc/stalwart-bootstrap/aws.env";
      stalwartPackage = pkgs.stalwart_0_16;
      cliPackage = pkgs.stalwart-cli;

      syncSecrets = pkgs.writeShellApplication {
        name = "sync-stalwart-aws-secrets";
        # The file is intentionally materialized by EC2 user data, outside the
        # Nix store, and therefore cannot be followed during the build check.
        excludeShellChecks = [ "SC1091" ];
        runtimeInputs = [
          pkgs.awscli2
          pkgs.coreutils
          pkgs.gnugrep
          pkgs.jq
          pkgs.systemd
        ];
        text = ''
          set -euo pipefail
          source ${deploymentEnvironment}

          install -d -m 0700 -o stalwart -g stalwart ${runtimeDirectory}
          changed=0

          install_secret() {
            local source_file="$1"
            local target_file="$2"
            if [[ ! -e "$target_file" ]] || ! cmp --silent "$source_file" "$target_file"; then
              install -m 0400 -o stalwart -g stalwart "$source_file" "$target_file"
              changed=1
            fi
          }

          rds_document="$(mktemp ${runtimeDirectory}/rds.XXXXXX)"
          trap 'rm -f "$rds_document" ${runtimeDirectory}/candidate.*' EXIT
          aws --region "$AWS_REGION" secretsmanager get-secret-value \
            --secret-id "$STALWART_RDS_SECRET_ARN" \
            --query SecretString --output text > "$rds_document"
          candidate="$(mktemp ${runtimeDirectory}/candidate.XXXXXX)"
          jq --exit-status --join-output '.password | select(type == "string" and length >= 20)' \
            "$rds_document" > "$candidate"
          install_secret "$candidate" ${runtimeDirectory}/rds-password
          rm -f "$candidate"

          for definition in \
            "admin:$STALWART_ADMIN_SECRET_ARN" \
            "mailbox:$STALWART_MAILBOX_SECRET_ARN" \
            "resend:$STALWART_RESEND_SECRET_ARN"; do
            name="''${definition%%:*}"
            arn="''${definition#*:}"
            candidate="$(mktemp ${runtimeDirectory}/candidate.XXXXXX)"
            if aws --region "$AWS_REGION" secretsmanager get-secret-value \
              --secret-id "$arn" --query SecretString --output text \
              > "$candidate" 2>/dev/null; then
              normalized="$(mktemp ${runtimeDirectory}/candidate.XXXXXX)"
              tr -d '\r\n' < "$candidate" > "$normalized"
              case "$name" in
                admin|mailbox)
                  grep -Eq '^[A-Za-z0-9]{40,128}$' "$normalized"
                  ;;
                resend)
                  grep -Eq '^re_[A-Za-z0-9_-]{20,509}$' "$normalized"
                  ;;
              esac
              install_secret "$normalized" "${runtimeDirectory}/$name-password"
              rm -f "$normalized"
            fi
            rm -f "$candidate"
          done

          if [[ "$changed" -eq 1 ]] && systemctl is-active --quiet stalwart.service; then
            systemctl try-restart stalwart.service
          fi
        '';
      };

      bootstrap = pkgs.writeShellApplication {
        name = "bootstrap-stalwart-aws";
        # The file is intentionally materialized by EC2 user data, outside the
        # Nix store, and therefore cannot be followed during the build check.
        excludeShellChecks = [ "SC1091" ];
        runtimeInputs = [
          pkgs.awscli2
          pkgs.coreutils
          pkgs.curl
          pkgs.jq
          pkgs.openssl
        ];
        text = ''
          set -euo pipefail
          source ${deploymentEnvironment}
          umask 077

          config_file=${stateDirectory}/config.json
          marker=${stateDirectory}/.bootstrap-complete
          admin_file=${runtimeDirectory}/admin-password
          mailbox_file=${runtimeDirectory}/mailbox-password

          test -r ${runtimeDirectory}/rds-password

          render_data_store() {
            jq --compact-output --null-input \
              --arg host "$STALWART_RDS_HOST" \
              '{
                "@type": "PostgreSql",
                host: $host,
                port: 5432,
                database: "stalwart",
                authUsername: "stalwart",
                authSecret: {"@type": "File", filePath: "${runtimeDirectory}/rds-password"},
                useTls: true,
                allowInvalidCerts: false,
                poolMaxConnections: 10
              }'
          }

          # A replacement EC2 root reconstructs the only local Stalwart file
          # from the managed RDS credential; all registry and mail state already
          # lives in RDS and S3.
          if [[ ! -e "$config_file" && -r "$admin_file" ]]; then
            render_data_store > "$config_file"
            chmod 0600 "$config_file"
            touch "$marker"
            exit 0
          fi

          for file in \
            ${stateDirectory}/bootstrap-recovery-password \
            ${stateDirectory}/bootstrap-admin-password \
            ${stateDirectory}/bootstrap-mailbox-password; do
            if [[ ! -s "$file" ]]; then
              openssl rand -hex 32 | tr -d '\n' > "$file"
              chmod 0600 "$file"
            fi
          done

          recovery_password="$(< ${stateDirectory}/bootstrap-recovery-password)"
          export STALWART_URL=http://127.0.0.1:8080
          export STALWART_USER=bootstrap
          export STALWART_PASSWORD="$recovery_password"
          export STALWART_RECOVERY_ADMIN="bootstrap:$recovery_password"
          if [[ -e "$config_file" ]]; then
            export STALWART_RECOVERY_MODE=true
          fi

          ${stalwartPackage}/bin/stalwart --config "$config_file" &
          server_pid=$!
          trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT

          for attempt in $(seq 1 120); do
            if curl --silent --output /dev/null http://127.0.0.1:8080/.well-known/jmap; then
              break
            fi
            test "$attempt" -lt 120
            sleep 1
          done

          if [[ ! -e "$config_file" ]]; then
            jq --compact-output --null-input \
              --arg host "$STALWART_RDS_HOST" \
              --arg bucket "$STALWART_BUCKET" \
              '{
                "@type": "update",
                object: "Bootstrap",
                value: {
                  serverHostname: "mail.fahrican.com",
                  defaultDomain: "fahrican.com",
                  requestTlsCertificate: true,
                  generateDkimKeys: true,
                  dataStore: {
                    "@type": "PostgreSql",
                    host: $host,
                    port: 5432,
                    database: "stalwart",
                    authUsername: "stalwart",
                    authSecret: {"@type": "File", filePath: "${runtimeDirectory}/rds-password"},
                    useTls: true,
                    allowInvalidCerts: false,
                    poolMaxConnections: 10
                  },
                  blobStore: {
                    "@type": "S3",
                    region: {"@type": "EuCentral1"},
                    bucket: $bucket,
                    keyPrefix: "blobs/",
                    maxRetries: 3,
                    timeout: 30000,
                    verifyAfterWrite: true,
                    allowInvalidCerts: false
                  },
                  searchStore: {"@type": "Default"},
                  inMemoryStore: {"@type": "Default"},
                  directory: {"@type": "Internal"},
                  tracer: {"@type": "Journal", level: "info"},
                  dnsServer: {"@type": "Manual"}
                }
              }' | ${cliPackage}/bin/stalwart-cli apply --stdin --json --quiet >/dev/null
            test -s "$config_file"
          fi

          jq --compact-output --null-input \
            --rawfile admin ${stateDirectory}/bootstrap-admin-password \
            --rawfile mailbox ${stateDirectory}/bootstrap-mailbox-password \
            '
              {"@type":"upsert","object":"Domain","matchOn":["name"],"value":{
                "primary-domain":{"name":"fahrican.com","isEnabled":true}
              }},
              {"@type":"upsert","object":"Account","matchOn":["name"],"value":{
                "admin-account":{
                  "@type":"User","name":"admin","domainId":"#primary-domain",
                  "description":"System administrator","roles":{"@type":"Admin"},
                  "credentials":[{"@type":"Password","secret":($admin | rtrimstr("\\n"))}]
                },
                "primary-mailbox":{
                  "@type":"User","name":"fahrican","domainId":"#primary-domain",
                  "description":"Fahrican","roles":{"@type":"User"},
                  "credentials":[{"@type":"Password","secret":($mailbox | rtrimstr("\\n"))}]
                }
              }},
              {"@type":"reconcile","object":"NetworkListener","matchOn":["name"],"value":{
                "smtp":{"name":"smtp","protocol":"smtp","bind":["[::]:25"],"useTls":true,"tlsImplicit":false},
                "submission":{"name":"submission","protocol":"smtp","bind":["[::]:587"],"useTls":true,"tlsImplicit":false},
                "submissions":{"name":"submissions","protocol":"smtp","bind":["[::]:465"],"useTls":true,"tlsImplicit":true},
                "imaptls":{"name":"imaptls","protocol":"imap","bind":["[::]:993"],"useTls":true,"tlsImplicit":true},
                "https":{"name":"https","protocol":"http","bind":["[::]:443"],"useTls":true,"tlsImplicit":true}
              }}
            ' | ${cliPackage}/bin/stalwart-cli apply --stdin --json --quiet >/dev/null

          install -m 0400 -o stalwart -g stalwart \
            ${stateDirectory}/bootstrap-admin-password "$admin_file"
          install -m 0400 -o stalwart -g stalwart \
            ${stateDirectory}/bootstrap-mailbox-password "$mailbox_file"
          aws --region "$AWS_REGION" secretsmanager put-secret-value \
            --secret-id "$STALWART_ADMIN_SECRET_ARN" \
            --secret-string "file://$admin_file" >/dev/null
          aws --region "$AWS_REGION" secretsmanager put-secret-value \
            --secret-id "$STALWART_MAILBOX_SECRET_ARN" \
            --secret-string "file://$mailbox_file" >/dev/null

          touch "$marker"
          rm -f \
            ${stateDirectory}/bootstrap-recovery-password \
            ${stateDirectory}/bootstrap-admin-password \
            ${stateDirectory}/bootstrap-mailbox-password
          unset STALWART_PASSWORD STALWART_RECOVERY_ADMIN recovery_password
        '';
      };

      reconcileRelay = pkgs.writeShellApplication {
        name = "reconcile-stalwart-resend";
        runtimeInputs = [ pkgs.jq ];
        text = ''
          set -euo pipefail
          export STALWART_URL=https://127.0.0.1:443
          export STALWART_USER=admin@fahrican.com
          export STALWART_PASSWORD="$(< ${runtimeDirectory}/admin-password)"

          jq --compact-output --null-input '
            {"@type":"upsert","object":"MtaRoute","matchOn":["name"],"value":{
              "resend":{
                "@type":"Relay","name":"resend","description":"Resend outbound relay",
                "address":"smtp.resend.com","port":587,"protocol":"smtp",
                "implicitTls":false,"allowInvalidCerts":false,"authUsername":"resend",
                "authSecret":{"@type":"File","filePath":"${runtimeDirectory}/resend-password"}
              }
            }},
            {"@type":"update","object":"MtaOutboundStrategy","value":{
              "route":{"match":[{"if":"is_local_domain(rcpt_domain)","then":"\u0027local\u0027"}],"else":"\u0027resend\u0027"}
            }}
          ' | ${cliPackage}/bin/stalwart-cli apply --insecure --stdin --json --quiet >/dev/null
          unset STALWART_PASSWORD
        '';
      };
    in
    {
      # The EC2 bootstrap creates this exact file before its first Nix
      # evaluation.  NixOS then owns its size and activation on every boot.
      swapDevices = [
        {
          device = "/swapfile";
          size = 2048;
        }
      ];

      users.groups.stalwart = { };
      users.users.stalwart = {
        isSystemUser = true;
        group = "stalwart";
        home = stateDirectory;
      };

      environment.systemPackages = [ cliPackage ];

      # The synchronization timer and the long-running daemon share this
      # tmpfs boundary. Let tmpfiles own its lifetime so one unit stopping
      # cannot remove credentials still in use by another unit.
      systemd.tmpfiles.rules = [
        "d ${runtimeDirectory} 0700 stalwart stalwart -"
      ];

      systemd.services = {
        stalwart-secrets = {
          description = "Synchronize Stalwart credentials from AWS Secrets Manager";
          after = [ "network-online.target" ];
          wants = [ "network-online.target" ];
          before = [
            "stalwart-bootstrap.service"
            "stalwart.service"
          ];
          unitConfig.ConditionPathExists = deploymentEnvironment;
          serviceConfig = {
            Type = "oneshot";
            ExecStart = "${syncSecrets}/bin/sync-stalwart-aws-secrets";
            UMask = "0077";
          };
        };

        stalwart-bootstrap = {
          description = "Bootstrap or reconstruct the declarative Stalwart registry";
          after = [ "stalwart-secrets.service" ];
          requires = [ "stalwart-secrets.service" ];
          before = [ "stalwart.service" ];
          unitConfig = {
            ConditionPathExists = [
              deploymentEnvironment
              "!${stateDirectory}/.bootstrap-complete"
            ];
          };
          serviceConfig = {
            Type = "oneshot";
            User = "stalwart";
            Group = "stalwart";
            ExecStart = "${bootstrap}/bin/bootstrap-stalwart-aws";
            StateDirectory = "stalwart";
            StateDirectoryMode = "0700";
            TimeoutStartSec = "10min";
            UMask = "0077";
          };
        };

        stalwart = {
          description = "Stalwart mail server";
          after = [
            "network-online.target"
            "stalwart-bootstrap.service"
            "stalwart-secrets.service"
          ];
          wants = [ "network-online.target" ];
          requires = [
            "stalwart-bootstrap.service"
            "stalwart-secrets.service"
          ];
          wantedBy = [ "multi-user.target" ];
          unitConfig.ConditionPathExists = [
            "${stateDirectory}/.bootstrap-complete"
            "${stateDirectory}/config.json"
            "${runtimeDirectory}/rds-password"
          ];
          serviceConfig = {
            User = "stalwart";
            Group = "stalwart";
            ExecStart = "${stalwartPackage}/bin/stalwart --config ${stateDirectory}/config.json";
            AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
            CapabilityBoundingSet = [ "CAP_NET_BIND_SERVICE" ];
            NoNewPrivileges = true;
            PrivateTmp = true;
            ProtectHome = true;
            ProtectSystem = "strict";
            ReadWritePaths = [ stateDirectory ];
            Restart = "always";
            RestartSec = 5;
            StateDirectory = "stalwart";
            StateDirectoryMode = "0700";
            UMask = "0077";
          };
        };

        stalwart-resend-reconcile = {
          description = "Reconcile the independently enrolled Resend route";
          after = [
            "stalwart.service"
            "stalwart-secrets.service"
          ];
          requires = [ "stalwart.service" ];
          unitConfig.ConditionPathExists = [
            "${runtimeDirectory}/admin-password"
            "${runtimeDirectory}/resend-password"
          ];
          serviceConfig = {
            Type = "oneshot";
            User = "stalwart";
            Group = "stalwart";
            ExecStart = "${reconcileRelay}/bin/reconcile-stalwart-resend";
            UMask = "0077";
          };
        };
      };

      systemd.timers = {
        stalwart-secrets = {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnBootSec = "5min";
            OnUnitActiveSec = "15min";
            RandomizedDelaySec = "2min";
            Persistent = true;
          };
        };
        stalwart-resend-reconcile = {
          wantedBy = [ "timers.target" ];
          timerConfig = {
            OnBootSec = "7min";
            OnUnitActiveSec = "30min";
            RandomizedDelaySec = "2min";
            Persistent = true;
          };
        };
      };

      networking = {
        hostName = "mail-aws";
        firewall.allowedTCPPorts = [
          25
          443
          465
          587
          993
        ];
      };

      assertions = [
        {
          assertion = config.services.amazon-ssm-agent.enable;
          message = "The AWS mail appliance requires Session Manager administration.";
        }
        {
          assertion = !config.services.openssh.openFirewall;
          message = "AWS mail administration must not expose SSH.";
        }
      ];
    };
}
