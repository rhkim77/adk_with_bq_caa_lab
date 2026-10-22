variable "project_id" {
  description = "Target Customer Google Cloud Project ID (e.g., my-enterprise-poc-project)"
  type        = string
}

variable "region" {
  description = "Primary GCP compute/Vertex AI region for ADK LLM invocations"
  type        = string
  default     = "us-central1"
}

variable "dataset_id" {
  description = "Target BigQuery dataset name to create for the BigQuery CAA + ADK Multi-Agent lab"
  type        = string
  default     = "thelook_ecommerce_agent"
}

variable "bq_location" {
  description = "BigQuery Dataset location. Default is 'US' (enables 15-second CTAS cloning from bigquery-public-data.thelook_ecommerce). If set to another region (e.g., 'asia-northeast3'), BigQuery Data Transfer Service cross_region_copy can be used."
  type        = string
  default     = "US"
}

variable "seed_demo_data" {
  description = "Whether to automatically clone bigquery-public-data.thelook_ecommerce and inject the 3-domain golden demo scenario data"
  type        = bool
  default     = true
}

variable "provision_caa_agents" {
  description = "Whether to automatically provision the 6 BigQuery Conversational Analytics (CAA) Data Agents via REST API after dataset preparation"
  type        = bool
  default     = true
}
