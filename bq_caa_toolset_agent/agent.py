"""Pattern A: ADK DataAgent Toolset Demo for `ryan-sandbox-agent.thelook_ecommerce`.

Wraps ADK's `google.adk.tools.data_agent.data_agent_tool` functions (`list_accessible_data_agents`,
`get_data_agent_info`, `ask_data_agent`) directly with Keyless ADC (`cloud-platform` scope),
avoiding the default `DATA_AGENT_DEFAULT_SCOPE = ['https://www.googleapis.com/auth/bigquery']`
in `google.adk.tools.data_agent.credentials.DataAgentCredentialsConfig` when `scopes` is omitted
(which can fail with 403 insufficient authentication scopes on GDA API).
"""

from __future__ import annotations

import os
from typing import Any

import google.auth
from google.adk.agents import LlmAgent
from google.adk.tools.data_agent import data_agent_tool
from google.adk.tools.data_agent.config import DataAgentToolConfig
from google.adk.tools.tool_context import ToolContext

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
if PROJECT_ID in ("", "your-gcp-project-id"):
  PROJECT_ID = "ryan-sandbox-agent"

DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
if not DATASET_ID:
  DATASET_ID = "thelook_ecommerce_agent"

GOVERNED_DATA_AGENT = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/thelook_governed_ca_agent"
)
BASELINE_DATA_AGENT = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/thelook_baseline_ca_agent"
)
SALES_KPI_DATA_AGENT = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/sales_kpi_ca_agent"
)

_TOOL_SETTINGS = DataAgentToolConfig(
    max_query_result_rows=50,
    location="global",
)


def _get_cloud_platform_adc():
  """Loads Keyless ADC with `cloud-platform` scope and quota project `ryan-sandbox-agent`."""
  creds, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  if hasattr(creds, "with_quota_project"):
    creds = creds.with_quota_project(PROJECT_ID)
  return creds


def list_accessible_data_agents(project_id: str = PROJECT_ID) -> dict[str, Any]:
  """Lists all accessible BigQuery Conversational Analytics Data Agents in the GCP project.

  Args:
      project_id: Target GCP project ID (defaults to 'ryan-sandbox-agent').
  """
  target_project = (
      PROJECT_ID
      if not project_id or project_id == "your-gcp-project-id"
      else project_id
  )
  return data_agent_tool.list_accessible_data_agents(
      project_id=target_project,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
  )


def get_data_agent_info(data_agent_name: str) -> dict[str, Any]:
  """Gets configuration, BigQuery table references, and system instruction of a Data Agent.

  Args:
      data_agent_name: Full resource name (`projects/{project}/locations/global/dataAgents/{id}`)
        or short agent ID (e.g., 'thelook_governed_ca_agent', 'thelook_baseline_ca_agent', 'sales_kpi_ca_agent').
  """
  if not data_agent_name.startswith("projects/"):
    data_agent_name = (
        f"projects/{PROJECT_ID}/locations/global/dataAgents/{data_agent_name}"
    )
  return data_agent_tool.get_data_agent_info(
      data_agent_name=data_agent_name,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
  )


def ask_data_agent(
    query: str,
    data_agent_name: str = GOVERNED_DATA_AGENT,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Asks a natural-language data analysis question to a BigQuery Conversational Analytics Data Agent.

  Args:
      query: Natural-language question in Korean or English.
      data_agent_name: Full resource name or short agent ID (defaults to `thelook_governed_ca_agent`).
  """
  if not data_agent_name.startswith("projects/"):
    data_agent_name = (
        f"projects/{PROJECT_ID}/locations/global/dataAgents/{data_agent_name}"
    )
  return data_agent_tool.ask_data_agent(
      data_agent_name=data_agent_name,
      query=query,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
      tool_context=tool_context,  # type: ignore[arg-type]
  )


root_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="bq_caa_toolset_agent",
    description=(
        "BigQuery Conversational Analytics (CAA) Agent for `thelook_ecommerce` "
        "powered by ADK data_agent_tool with Keyless cloud-platform ADC."
    ),
    instruction=(
        f"당신은 `{PROJECT_ID}.{DATASET_ID}` 이커머스 데이터를 분석하는 BigQuery Conversational Analytics (CAA) 코디네이터입니다.\n"
        f"- 기본 GCP 프로젝트 ID: `{PROJECT_ID}`\n"
        f"- **기본(Governed) Data Agent**: `{GOVERNED_DATA_AGENT}` (비즈니스 용어집: VIP/우수 고객, 휴면/이탈 고객, 장바구니 이탈율, 상품 마진율, 환불률 규칙 적용됨)\n"
        f"- **비교용(Baseline) Data Agent**: `{BASELINE_DATA_AGENT}` (비즈니스 용어집 미적용, 순수 테이블 스키마만 연결됨)\n"
        f"- **호환 별칭(Alias) Data Agent**: `{SALES_KPI_DATA_AGENT}`\n\n"
        "[도구 사용 지침]\n"
        f"1. 등록된 에이전트 목록 요청 시 `list_accessible_data_agents(project_id='{PROJECT_ID}')`를 호출하세요.\n"
        "2. 특정 에이전트(예: `thelook_governed_ca_agent`, `thelook_baseline_ca_agent`, `sales_kpi_ca_agent`)의 상세 설정/테이블 확인 요청 시 "
        "`get_data_agent_info(data_agent_name=...)`를 호출하세요.\n"
        "3. 일반적인 데이터 분석 질문은 기본적으로 **Governed 에이전트**(`thelook_governed_ca_agent`)에 `ask_data_agent`를 호출하세요.\n"
        "4. 사용자가 'Baseline과 Governed 에이전트 결과를 비교해줘'라고 요청하면 두 에이전트에 각각 `ask_data_agent`를 호출하여 생성된 SQL과 결과 차이를 비교 표로 정리해 주세요.\n"
        "5. 만약 도구 호출 결과에 `status: ERROR`가 반환되면 `error_details` 원문을 숨기지 말고 그대로 사용자에게 보여주세요.\n"
        "6. 정상 답변 시 생성된 SQL(`generatedSql`), 조회된 데이터 표(`Data Retrieved`), 그리고 최종 분석 요약을 마크다운으로 깔끔하게 출력하세요."
    ),
    tools=[
        list_accessible_data_agents,
        get_data_agent_info,
        ask_data_agent,
    ],
)
