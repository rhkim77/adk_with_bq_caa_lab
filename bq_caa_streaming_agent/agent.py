"""Pattern B: Deterministic CA-First Multi-Turn Streaming & State-Sharing Demo for `thelook_ecommerce`.

Implements `ca-api-adk-streaming` pattern on `ryan-sandbox-agent.thelook_ecommerce`:
1. `ConversationalAnalyticsStreamingAgent` (BaseAgent):
   - Reconstructs Multi-Turn conversation history from `ctx.session.events`.
   - Calls `projects/ryan-sandbox-agent/locations/global/dataAgents/thelook_governed_ca_agent` via `:chat`.
   - Streams THOUGHT, Generated SQL, and Markdown Result Table.
   - Saves structured rows into `ctx.session.state['temp:data_result']` and summary into `ctx.session.state['temp:summary_data']`.
2. `ExecutiveInsightSubAgent` (LlmAgent):
   - Triggered conditionally (`run_when`) only when `temp:data_result` is populated.
   - Reads `{temp:data_result}` and `{temp:summary_data}` from session state with zero redundant BigQuery queries.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncGenerator, Callable, NamedTuple

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.genai import types

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
if PROJECT_ID in ("", "your-gcp-project-id"):
  PROJECT_ID = "ryan-sandbox-agent"

DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
if not DATASET_ID:
  DATASET_ID = "thelook_ecommerce_agent"

DATA_AGENT_ID = os.environ.get("CAA_DATA_AGENT_ID", "thelook_governed_ca_agent")
DATA_AGENT_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_ID}"
)


def _build_multiturn_ca_messages(ctx: InvocationContext) -> list[dict[str, Any]]:
  """Converts ADK `ctx.session.events` into BigQuery CAA Multi-Turn `messages` array."""
  messages: list[dict[str, Any]] = []
  for ev in ctx.session.events:
    if not ev.content or not ev.content.parts:
      continue
    text = "\n".join(
        p.text for p in ev.content.parts if getattr(p, "text", None)
    ).strip()
    if not text:
      continue

    if ev.content.role == "user":
      messages.append({"userMessage": {"text": text}})
    elif ev.author == "ca_query_agent":
      messages.append({"systemMessage": {"text": {"parts": [text]}}})
  return messages


def _format_markdown_table(rows: list[dict[str, Any]], max_rows: int = 20) -> str:
  if not rows:
    return ""
  headers = list(rows[0].keys())
  header_line = "| " + " | ".join(headers) + " |"
  sep_line = "| " + " | ".join("---" for _ in headers) + " |"
  body_lines = []
  for r in rows[:max_rows]:
    body_lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
  footer = (
      f"\n*(Showing top {max_rows} of {len(rows)} rows)*"
      if len(rows) > max_rows
      else f"\n*(Total {len(rows)} rows)*"
  )
  return "\n".join([header_line, sep_line, *body_lines]) + footer


def _call_caa_stream_sync(
    project_id: str,
    data_agent_name: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  """Calls Gemini Data Analytics `:chat` streaming endpoint using Keyless ADC."""
  credentials, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  credentials = credentials.with_quota_project(project_id)
  session = AuthorizedSession(credentials)

  url = f"https://geminidataanalytics.googleapis.com/v1/projects/{project_id}/locations/global:chat"
  payload = {
      "messages": messages,
      "dataAgentContext": {"dataAgent": data_agent_name},
  }
  headers = {
      "Content-Type": "application/json",
  }

  chunks: list[dict[str, Any]] = []
  accumulator = ""
  with session.post(url, json=payload, headers=headers, stream=True, timeout=120) as resp:
    if not resp.ok:
      raise RuntimeError(f"CAA API HTTP {resp.status_code}: {resp.text}")
    for line in resp.iter_lines():
      if not line:
        continue
      decoded = line.decode("utf-8")
      if decoded == "[{":
        accumulator = "{"
      elif decoded == "}]":
        accumulator += "}"
      elif decoded == ",":
        continue
      else:
        accumulator += decoded
      try:
        parsed = json.loads(accumulator)
        accumulator = ""
        if isinstance(parsed, dict):
          chunks.append(parsed)
      except ValueError:
        continue
  return chunks


class ConversationalAnalyticsStreamingAgent(BaseAgent):
  """Deterministic CA-First Sub-Agent that streams SQL, Data, and Summary while populating `temp:*` state."""

  async def _run_async_impl(
      self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    ctx.session.state["temp:data_result"] = None
    ctx.session.state["temp:summary_data"] = None

    messages = _build_multiturn_ca_messages(ctx)
    if not messages:
      return

    try:
      chunks = await asyncio.to_thread(
          _call_caa_stream_sync, PROJECT_ID, DATA_AGENT_RESOURCE, messages
      )
    except Exception as exc:
      err_text = (
          f"⚠️ **BigQuery CAA 호출 오류**: `{exc}`\n\n"
          "먼저 터미널에서 `python3 provision_bq_caa_demo.py`를 실행하여 `ryan-sandbox-agent.thelook_ecommerce` 기반의 "
          f"`{DATA_AGENT_RESOURCE}` 에이전트를 생성했는지 확인해 주세요."
      )
      yield Event(
          invocation_id=ctx.invocation_id,
          author=self.name,
          content=types.Content(role="model", parts=[types.Part.from_text(text=err_text)]),
      )
      return

    rendered_sections: list[str] = []
    summary_parts: list[str] = []

    for item in chunks:
      sm = item.get("systemMessage", {})
      if not isinstance(sm, dict):
        continue

      # 1. Text (THOUGHT or FINAL_RESPONSE)
      if "text" in sm and isinstance(sm["text"], dict):
        parts = sm["text"].get("parts", [])
        text_type = sm["text"].get("textType", "")
        joined = "".join(str(p) for p in parts).strip()
        if joined:
          if text_type in ("THOUGHT", "PROGRESS"):
            rendered_sections.append(f"> 💭 **[CA 추론]** {joined}")
          else:
            summary_parts.append(joined)

      # 2. Generated SQL & Result Data
      if "data" in sm and isinstance(sm["data"], dict):
        data_obj = sm["data"]
        gen_sql = data_obj.get("generatedSql")
        if gen_sql:
          rendered_sections.append(f"### 1. 생성된 BigQuery SQL (`thelook_ecommerce`)\n```sql\n{gen_sql.strip()}\n```")

        result_obj = data_obj.get("result")
        if isinstance(result_obj, dict) and isinstance(result_obj.get("data"), list):
          rows = result_obj["data"]
          ctx.session.state["temp:data_result"] = rows
          table_md = _format_markdown_table(rows, max_rows=20)
          if table_md:
            rendered_sections.append(f"### 2. 조회 결과 데이터 (`temp:data_result` 저장됨)\n{table_md}")

    final_summary = "\n\n".join(summary_parts).strip()
    if final_summary:
      ctx.session.state["temp:summary_data"] = final_summary
      rendered_sections.append(f"### 3. CA 분석 요약 (`temp:summary_data`)\n{final_summary}")

    full_output = "\n\n".join(rendered_sections).strip() or "응답 데이터가 없습니다."
    yield Event(
        invocation_id=ctx.invocation_id,
        author=self.name,
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=full_output)],
        ),
    )


class OptionalAgentSpec(NamedTuple):
  agent: BaseAgent
  run_when: Callable[[InvocationContext], bool]


class CaStreamingOrchestrator(BaseAgent):
  """Deterministic Root Orchestrator (`ca-api-adk-streaming` pattern)."""

  ca_query_agent: BaseAgent
  optional_agents: list[OptionalAgentSpec] = []

  async def _run_async_impl(
      self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    async for event in self.ca_query_agent.run_async(ctx):
      yield event

    for spec in self.optional_agents:
      if spec.run_when(ctx):
        async for event in spec.agent.run_async(ctx):
          yield event


executive_insight_agent = LlmAgent(
    name="executive_insight_subagent",
    model="gemini-2.5-flash",
    description="Generates 3 executive e-commerce insights from `temp:data_result` without re-querying BigQuery.",
    instruction=(
        "당신은 이커머스 경영진 의사결정 지원(Executive Insight) 서브 에이전트입니다.\n"
        "앞선 `ca_query_agent`가 `thelook_ecommerce` 데이터셋에서 조회하여 세션 상태(`ctx.session.state`)에 저장한 "
        "정형 데이터와 요약을 바탕으로 **3가지 핵심 마케팅/MD/물류 비즈니스 시사점 및 액션 아이템**을 한국어 불릿 포인트로 제시하세요.\n\n"
        "- 조회된 정형 데이터 (`temp:data_result`):\n{temp:data_result}\n\n"
        "- CA 요약 (`temp:summary_data`):\n{temp:summary_data}\n"
    ),
)

ca_query_agent = ConversationalAnalyticsStreamingAgent(
    name="ca_query_agent",
    description="Streams Multi-Turn BigQuery Conversational Analytics (CAA) queries on `thelook_ecommerce` and populates temp:data_result.",
)

root_agent = CaStreamingOrchestrator(
    name="bq_caa_streaming_agent",
    description="Deterministic CA-First Multi-Turn Streaming Orchestrator on `thelook_ecommerce` with Conditional Executive Insight Sub-Agent.",
    sub_agents=[ca_query_agent, executive_insight_agent],
    ca_query_agent=ca_query_agent,
    optional_agents=[
        OptionalAgentSpec(
            agent=executive_insight_agent,
            run_when=lambda ctx: bool(ctx.session.state.get("temp:data_result")),
        )
    ],
)
