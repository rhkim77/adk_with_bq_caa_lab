"""Multi-Agent Hierarchy Demo for ADK Web UI (Agent Graph & Event Trace)."""

from google.adk.agents import LlmAgent


def query_sales_summary(region: str, quarter: str = 'Q3') -> dict:
  """Queries sample regional sales KPI metrics.

  Args:
      region: Target region (e.g., 'KR', 'APAC', 'NA', 'EU').
      quarter: Fiscal quarter (e.g., 'Q1', 'Q2', 'Q3', 'Q4').
  """
  mock_metrics = {
      'KR': {'revenue_musd': 142.5, 'yoy_growth': '+14.2%', 'top_sku': 'OLED-77'},
      'APAC': {'revenue_musd': 310.0, 'yoy_growth': '+11.8%', 'top_sku': 'QNED-65'},
      'NA': {'revenue_musd': 580.4, 'yoy_growth': '+9.5%', 'top_sku': 'OLED-83'},
  }
  key = region.strip().upper()
  return {
      'status': 'success',
      'region': key,
      'quarter': quarter,
      'metrics': mock_metrics.get(
          key, {'revenue_musd': 95.0, 'yoy_growth': '+7.0%', 'top_sku': 'STANDBYME'}
      ),
  }


def check_security_compliance(data_classification: str, region: str) -> dict:
  """Checks GCP data residency and CMEK/VPC-SC compliance requirements.

  Args:
      data_classification: Classification tier ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'PII').
      region: GCP deployment region (e.g., 'asia-northeast3', 'us-central1', 'global').
  """
  tier = data_classification.strip().upper()
  requires_cmek = tier in ('CONFIDENTIAL', 'PII')
  return {
      'status': 'success',
      'classification': tier,
      'region': region,
      'requires_cmek': requires_cmek,
      'requires_vpc_sc': requires_cmek,
      'model_armor_policy': 'STRICT_PII_MASKING' if tier == 'PII' else 'STANDARD',
  }


analytics_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='analytics_specialist',
    description='Handles regional sales KPI queries, revenue analysis, and YoY growth lookups.',
    instruction=(
        'You are a Data Analytics Specialist. Use `query_sales_summary` to fetch '
        'regional sales KPIs and summarize the findings clearly.'
    ),
    tools=[query_sales_summary],
)

security_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='security_governance_specialist',
    description='Handles GCP security compliance, CMEK, VPC-SC, and PII governance checks.',
    instruction=(
        'You are a Cloud Security & Governance Specialist. Use `check_security_compliance` '
        'to evaluate data residency, CMEK, VPC-SC, and Model Armor requirements.'
    ),
    tools=[check_security_compliance],
)

root_agent = LlmAgent(
    model='gemini-2.5-flash',
    name='enterprise_router_agent',
    description='Root orchestrator routing between Data Analytics and Security Governance specialists.',
    instruction=(
        'You are an Enterprise Coordinator Agent.\n'
        '- Delegate sales/revenue/KPI questions to `analytics_specialist`.\n'
        '- Delegate security/CMEK/VPC-SC/PII compliance questions to `security_governance_specialist`.\n'
        '- Answer general greetings directly and explain your available sub-agents.'
    ),
    sub_agents=[analytics_agent, security_agent],
)
