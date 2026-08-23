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
      rdsCaBundle = pkgs.fetchurl {
        name = "aws-rds-eu-central-1-ca-bundle.pem";
        url = "https://truststore.pki.rds.amazonaws.com/eu-central-1/eu-central-1-bundle.pem";
        hash = "sha256-VqDK4ES2zEM5cdlkNHQBaSqS6gKU45J1Oj69ruVNi4Q=";
      };

      syncSecrets = pkgs.writeShellApplication {
        name = "sync-stalwart-aws-secrets";
        runtimeInputs = [
          pkgs.awscli2
          pkgs.coreutils
          pkgs.gnugrep
          pkgs.jq
          pkgs.systemd
        ];
        text = ''
          set -euo pipefail

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
            # Stalwart requires this oneshot unit. Queueing its restart avoids
            # waiting for a job that cannot start until this unit has exited.
            systemctl --no-block try-restart stalwart.service
          fi
        '';
      };

      bootstrap = pkgs.writeShellApplication {
        name = "bootstrap-stalwart-aws";
        runtimeInputs = [
          pkgs.awscli2
          pkgs.coreutils
          pkgs.curl
          pkgs.jq
          pkgs.openssl
          pkgs.postgresql
        ];
        text = ''
          set -euo pipefail
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

          write_data_store_config() {
            render_data_store > "$config_file"
            chmod 0600 "$config_file"
          }

          # A replacement EC2 root reconstructs the only local Stalwart file
          # from the managed RDS credential; all registry and mail state already
          # lives in RDS and S3.
          if [[ ! -e "$config_file" && -r "$admin_file" ]]; then
            write_data_store_config
            touch "$marker"
            exit 0
          fi

          if [[ ! -e "$config_file" ]]; then
            PGPASSWORD="$(< ${runtimeDirectory}/rds-password)"
            export PGPASSWORD
            registry_initialized="$(
              PGSSLMODE=verify-full \
                PGSSLROOTCERT=${rdsCaBundle} \
                psql \
                  --host "$STALWART_RDS_HOST" \
                  --port 5432 \
                  --dbname stalwart \
                  --username stalwart \
                  --tuples-only \
                  --no-align \
                  --set ON_ERROR_STOP=1 \
                  --command "SELECT to_regclass('public.s') IS NOT NULL;"
            )"
            unset PGPASSWORD

            case "$registry_initialized" in
              t)
                # `s` is the registry table in the pinned Stalwart schema.
                # Its presence distinguishes an interrupted bootstrap from a
                # pristine database without relying on human-facing errors.
                write_data_store_config
                ;;
              f) ;;
              *)
                echo "Unexpected Stalwart registry probe result." >&2
                exit 1
                ;;
            esac
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

          server_pid=

          stop_server() {
            if [[ -n "$server_pid" ]]; then
              kill "$server_pid" 2>/dev/null || true
              wait "$server_pid" 2>/dev/null || true
              server_pid=
            fi
          }

          start_server() {
            ${stalwartPackage}/bin/stalwart --config "$config_file" &
            server_pid=$!

            for _ in $(seq 1 120); do
              if curl --silent --output /dev/null http://127.0.0.1:8080/.well-known/jmap; then
                return 0
              fi
              if ! kill -0 "$server_pid" 2>/dev/null; then
                wait "$server_pid" 2>/dev/null || true
                server_pid=
                return 1
              fi
              sleep 1
            done

            return 1
          }

          trap stop_server EXIT
          if [[ -e "$config_file" ]]; then
            export STALWART_RECOVERY_MODE=true
          fi
          start_server

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
            stop_server
            export STALWART_RECOVERY_MODE=true
            start_server
          fi

          # Until publication completes, these local files are the source of
          # truth. Reconcile both account passwords from them on every retry
          # so an interrupted bootstrap or replaced root volume cannot publish
          # credentials that differ from the durable RDS accounts.
          jq --compact-output --null-input \
            --rawfile admin ${stateDirectory}/bootstrap-admin-password \
            --rawfile mailbox ${stateDirectory}/bootstrap-mailbox-password \
            '
              def password($secret):
                {"0":{"@type":"Password","secret":($secret | rtrimstr("\\n"))}};
              {"@type":"upsert","object":"Domain","matchOn":["name"],"value":{
                "primary-domain":{"name":"fahrican.com","isEnabled":true}
              }},
              {"@type":"upsert","object":"Account","matchOn":["name"],"value":{
                "admin-account":{
                  "@type":"User","name":"admin","domainId":"#primary-domain",
                  "description":"System administrator","roles":{"@type":"Admin"},
                  "credentials":password($admin)
                },
                "primary-mailbox":{
                  "@type":"User","name":"fahrican","domainId":"#primary-domain",
                  "description":"Fahrican","roles":{"@type":"User"},
                  "credentials":password($mailbox)
                }
              }},
              {"@type":"reconcile","object":"NetworkListener","matchOn":["name"],"value":{
                "smtp":{"name":"smtp","protocol":"smtp","bind":{"[::]:25":true},"useTls":true,"tlsImplicit":false},
                "submission":{"name":"submission","protocol":"smtp","bind":{"[::]:587":true},"useTls":true,"tlsImplicit":false},
                "submissions":{"name":"submissions","protocol":"smtp","bind":{"[::]:465":true},"useTls":true,"tlsImplicit":true},
                "imaptls":{"name":"imaptls","protocol":"imap","bind":{"[::]:993":true},"useTls":true,"tlsImplicit":true},
                "https":{"name":"https","protocol":"http","bind":{"[::]:443":true},"useTls":true,"tlsImplicit":true}
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
          STALWART_PASSWORD="$(< ${runtimeDirectory}/admin-password)"
          export STALWART_PASSWORD

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
              "route/match/0/if":"is_local_domain(rcpt_domain)",
              "route/match/0/then":"\u0027local\u0027",
              "route/else":"\u0027resend\u0027"
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
      # Stalwart 0.16 validates PostgreSQL through the platform trust store.
      # RDS uses AWS-private roots, so add the official regional bundle while
      # retaining hostname and certificate validation.
      security.pki.certificateFiles = [ rdsCaBundle ];

      # EC2 user data materializes only non-secret deployment metadata.
      # systemd reads this root-only file before applying each service's user
      # boundary, so scripts depend on an injected environment rather than
      # filesystem access.  Tmpfiles also owns the shared runtime boundary so
      # one unit stopping cannot remove credentials still used by another.
      systemd.tmpfiles.rules = [
        "d /etc/stalwart-bootstrap 0750 root root -"
        "z ${deploymentEnvironment} 0600 root root -"
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
            EnvironmentFile = deploymentEnvironment;
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
            EnvironmentFile = deploymentEnvironment;
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
