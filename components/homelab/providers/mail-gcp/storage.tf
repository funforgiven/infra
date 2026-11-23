resource "google_sql_database_instance" "mail" {
  name                = "stalwart"
  database_version    = "POSTGRES_17"
  region              = local.region
  deletion_protection = true
  depends_on          = [google_service_networking_connection.sql]
  settings {
    edition                     = "ENTERPRISE"
    tier                        = "db-f1-micro"
    availability_type           = "ZONAL"
    disk_type                   = "PD_HDD"
    disk_size                   = 10
    disk_autoresize             = true
    disk_autoresize_limit       = 30
    deletion_protection_enabled = true
    location_preference {
      zone = local.zone
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.mail.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
    backup_configuration {
      enabled                        = true
      start_time                     = "01:00"
      location                       = "eu"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
      }
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_sql_database" "mail" {
  name     = "stalwart"
  instance = google_sql_database_instance.mail.name
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_sql_user" "mail" {
  name     = trimsuffix(google_service_account.vm.email, ".gserviceaccount.com")
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
  instance = google_sql_database_instance.mail.name
}

resource "google_storage_bucket" "blobs" {
  name                        = "${var.project_id}-blobs"
  location                    = local.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  depends_on                  = [google_project_service.mail]
  versioning {
    enabled = true
  }
  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      with_state                 = "ARCHIVED"
      days_since_noncurrent_time = 90
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_storage_bucket_iam_member" "blobs" {
  bucket = google_storage_bucket.blobs.name
  role   = "roles/storage.objectUser"
  member = google_service_account.blobs.member
}

resource "google_secret_manager_secret" "runtime" {
  for_each  = toset(["admin", "mailbox", "resend", "canary", "backup", "gcs-hmac"])
  secret_id = "mail-${each.key}"
  replication {
    user_managed {
      replicas {
        location = local.region
      }
    }
  }
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [google_project_service.mail]
}

resource "google_secret_manager_secret_iam_member" "vm" {
  for_each  = google_secret_manager_secret.runtime
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.vm.member
}
