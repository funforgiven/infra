terraform {
  required_version = ">= 1.12.1, < 2.0.0"
  backend "gcs" {
    prefix = "opentofu/mail"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 8.12.0"
    }
  }
}

variable "project_id" {
  type = string
}

variable "alert_email" {
  type        = string
  description = "Operator mailbox outside fahrican.com for independent delivery of alerts"
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.alert_email)) && !endswith(lower(var.alert_email), "@fahrican.com")
    error_message = "Use an external notification mailbox that remains available during a mail outage."
  }
}

variable "enable_runtime" {
  description = "Start Stalwart after the database, blobs and runtime secrets have been migrated"
  type        = bool
  default     = false
}

variable "monitor_delivery" {
  description = "Enable public checks and the delivery canary once Cloudflare publishes the live MX"
  type        = bool
  default     = false
  validation {
    condition     = !var.monitor_delivery || var.enable_runtime
    error_message = "Delivery checks require the running mail service."
  }
}

locals {
  region = "europe-west1"
  zone   = "europe-west1-b"
  host_files = {
    "mail-setup"      = file("${path.module}/../../services/mail-gcp/setup.sh")
    "mail-configure"  = file("${path.module}/../../services/mail-gcp/configure.py")
    "mail-operations" = file("${path.module}/../../services/mail-aws/operations.py")
  }
}

provider "google" {
  billing_project       = var.project_id
  user_project_override = true
  project               = var.project_id
  region                = local.region
  zone                  = local.zone
}

resource "google_project_service" "mail" {
  for_each = toset([
    "compute.googleapis.com", "iam.googleapis.com", "iap.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "oslogin.googleapis.com", "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_compute_network" "mail" {
  name                    = "mail"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.mail]
}

resource "google_compute_subnetwork" "mail" {
  name                     = "mail"
  network                  = google_compute_network.mail.id
  ip_cidr_range            = "10.91.0.0/28"
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql" {
  name          = "mail-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 24
  network       = google_compute_network.mail.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.mail.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql.name]
}

resource "google_compute_address" "mail" {
  name       = "mail"
  depends_on = [google_project_service.mail]
}

resource "google_service_account" "vm" {
  account_id   = "mail-runtime"
  display_name = "Stalwart VM"
  depends_on   = [google_project_service.mail]
}

resource "google_service_account" "blobs" {
  account_id   = "mail-blobs"
  display_name = "Stalwart GCS interoperable storage"
  depends_on   = [google_project_service.mail]
}

resource "google_project_iam_member" "vm" {
  for_each = toset(["roles/cloudsql.client", "roles/cloudsql.instanceUser", "roles/logging.logWriter", "roles/monitoring.metricWriter"])
  project  = var.project_id
  role     = each.key
  member   = google_service_account.vm.member
}

resource "google_compute_firewall" "mail" {
  name                    = "mail-public"
  network                 = google_compute_network.mail.name
  source_ranges           = ["0.0.0.0/0"]
  target_service_accounts = [google_service_account.vm.email]
  allow {
    protocol = "tcp"
    ports    = ["25", "443"]
  }
}

resource "google_compute_firewall" "iap" {
  name                    = "mail-iap-ssh"
  network                 = google_compute_network.mail.name
  source_ranges           = ["35.235.240.0/20"]
  target_service_accounts = [google_service_account.vm.email]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "mail" {
  name         = "stalwart"
  machine_type = "e2-micro"
  zone         = local.zone

  boot_disk {
    auto_delete = true
    initialize_params {
      image = "debian-cloud/debian-13"
      type  = "pd-standard"
      size  = 20
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.mail.id
    access_config {
      nat_ip = google_compute_address.mail.address
    }
  }
  service_account {
    email  = google_service_account.vm.email
    scopes = ["cloud-platform"]
  }
  shielded_instance_config {
    enable_secure_boot = true
  }
  metadata = merge(local.host_files, {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    mail-project           = var.project_id
    mail-sql               = google_sql_database_instance.mail.connection_name
    mail-db-user           = google_sql_user.mail.name
    mail-bucket            = google_storage_bucket.blobs.name
    mail-runtime           = tostring(var.enable_runtime)
    mail-monitor           = tostring(var.monitor_delivery)
  })
  # File or phase changes rebuild the disposable host and rerun the same boot sequence.
  metadata_startup_script = <<-SCRIPT
    #!/bin/bash
    set -euo pipefail
    # Revision ${sha256(jsonencode([local.host_files, var.enable_runtime]))}
    install -d /usr/local/lib/mail
    for file in mail-setup mail-configure mail-operations; do
      curl --fail --silent --show-error --retry 5 -H 'Metadata-Flavor: Google' \
        "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$file" \
        -o "/usr/local/lib/mail/$file"
    done
    exec bash /usr/local/lib/mail/mail-setup
  SCRIPT
  depends_on              = [google_project_iam_member.vm, google_secret_manager_secret_iam_member.vm, google_sql_database.mail]
}

output "ipv4_address" {
  value = google_compute_address.mail.address
}
output "blob_bucket" {
  value = google_storage_bucket.blobs.name
}
output "sql_user" {
  value = google_sql_user.mail.name
}
