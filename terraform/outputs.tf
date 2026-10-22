output "gcp_project_id" {
  description = "Customer GCP Project ID"
  value       = var.project_id
}

output "bigquery_dataset_full_id" {
  description = "Provisioned BigQuery Dataset ID (`project.dataset`)"
  value       = "${var.project_id}.${google_bigquery_dataset.thelook_ecommerce_agent.dataset_id}"
}

output "bigquery_dataset_location" {
  description = "BigQuery Dataset Location"
  value       = google_bigquery_dataset.thelook_ecommerce_agent.location
}

output "caa_single_agents" {
  description = "Single-Agent & Before/After Governance Demo CAA Resource Names"
  value = {
    governed = "projects/${var.project_id}/locations/global/dataAgents/thelook_governed_ca_agent"
    baseline = "projects/${var.project_id}/locations/global/dataAgents/thelook_baseline_ca_agent"
  }
}

output "caa_3domain_subagents" {
  description = "3 Domain-Scoped BigQuery CAA Sub-Agents for Root Router Architecture"
  value = {
    domain_1_customer_marketing    = "projects/${var.project_id}/locations/global/dataAgents/thelook_customer_marketing_ca"
    domain_2_product_profitability = "projects/${var.project_id}/locations/global/dataAgents/thelook_product_profitability_ca"
    domain_3_supply_chain          = "projects/${var.project_id}/locations/global/dataAgents/thelook_supply_chain_ca"
  }
}

output "next_step_launch_adk_web" {
  description = "Command to launch the Google ADK Web UI"
  value       = "./setup_mac_adk.sh ${var.project_id} ${var.dataset_id}"
}
