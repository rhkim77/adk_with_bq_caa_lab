# =============================================================================
# 1. Enable Required Google Cloud APIs on Customer Project
# =============================================================================
locals {
  required_apis = [
    "bigquery.googleapis.com",
    "bigquerydatatransfer.googleapis.com",
    "geminidataanalytics.googleapis.com",
    "cloudaicompanion.googleapis.com",
    "aiplatform.googleapis.com",
    "dataplex.googleapis.com",
    "datacatalog.googleapis.com",
  ]
}

resource "google_project_service" "enabled_apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# =============================================================================
# 2. Create Target BigQuery Dataset (`thelook_ecommerce_agent`, default `US`)
# =============================================================================
resource "google_bigquery_dataset" "thelook_ecommerce_agent" {
  project                    = var.project_id
  dataset_id                 = var.dataset_id
  friendly_name              = "TheLook eCommerce Agentic Demo Dataset"
  description                = "Cloned from bigquery-public-data.thelook_ecommerce and augmented with 3-Domain Golden Demo Scenarios for BigQuery CAA + Google ADK Multi-Agent Hands-on Lab."
  location                   = var.bq_location
  delete_contents_on_destroy = true

  labels = {
    environment = "demo-lab"
    architecture = "bq-caa-adk-multiagent"
  }

  depends_on = [google_project_service.enabled_apis]
}

# =============================================================================
# 3. Optional Cross-Region Copy via BigQuery Data Transfer Service
#    (Only created when customer overrides `var.bq_location != "US"`)
# =============================================================================
resource "google_bigquery_data_transfer_config" "cross_region_thelook_copy" {
  count                  = upper(var.bq_location) != "US" ? 1 : 0
  project                = var.project_id
  display_name           = "Copy public thelook_ecommerce to ${var.dataset_id} (${var.bq_location})"
  location               = var.bq_location
  data_source_id         = "cross_region_copy"
  destination_dataset_id = google_bigquery_dataset.thelook_ecommerce_agent.dataset_id

  schedule_options {
    disable_auto_scheduling = false
  }

  params = {
    source_project_id = "bigquery-public-data"
    source_dataset_id = "thelook_ecommerce"
    overwrite_destination_table = "true"
  }

  depends_on = [google_bigquery_dataset.thelook_ecommerce_agent]
}

# =============================================================================
# 4. Clone 7 Tables (CTAS in `US`) + Seed Golden Demo Data (`sql/01` & `sql/02`)
# =============================================================================
resource "null_resource" "prepare_bigquery_demo_data" {
  count = var.seed_demo_data && upper(var.bq_location) == "US" ? 1 : 0

  triggers = {
    project_id  = var.project_id
    dataset_id  = google_bigquery_dataset.thelook_ecommerce_agent.dataset_id
    bq_location = var.bq_location
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    environment = {
      GOOGLE_CLOUD_PROJECT = var.project_id
      BQ_DATASET_ID        = google_bigquery_dataset.thelook_ecommerce_agent.dataset_id
      BQ_LOCATION          = var.bq_location
    }
    command = "python3 scripts/01_prepare_bigquery_data.py"
  }

  depends_on = [google_bigquery_dataset.thelook_ecommerce_agent]
}

# =============================================================================
# 5. Provision 6 BigQuery CAA Data Agents (Single + 3 Domain Sub-Agents)
# =============================================================================
resource "null_resource" "provision_bq_caa_agents" {
  count = var.provision_caa_agents ? 1 : 0

  triggers = {
    project_id = var.project_id
    dataset_id = google_bigquery_dataset.thelook_ecommerce_agent.dataset_id
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    environment = {
      GOOGLE_CLOUD_PROJECT = var.project_id
      BQ_DATASET_ID        = google_bigquery_dataset.thelook_ecommerce_agent.dataset_id
    }
    command = "python3 provision_bq_caa_demo.py"
  }

  depends_on = [
    google_bigquery_dataset.thelook_ecommerce_agent,
    null_resource.prepare_bigquery_demo_data,
  ]
}
