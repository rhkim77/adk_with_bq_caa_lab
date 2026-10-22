"""Hierarchical Multi-Agent Architecture: Root Router Agent + 3 Domain-Scoped BigQuery CAA Sub-Agents
with Full ADK Session Object (4-Scope State + Multi-Turn History) & Memory Object (Long-Term Memory Bank).

Dataset: `ryan-sandbox-agent.thelook_ecommerce`

Architecture:
  [Root Agent] `thelook_enterprise_root_router` (LlmAgent)
    ├─ Session Management (`ctx.session` & 4 State Scopes):
    │    - `temp:*`   : Turn-scoped SQL, row count, and preview rows (`temp:last_caa_sql`, `temp:last_caa_rows`)
    │    - `session`  : Session-scoped multi-turn query history (`domain_query_history`, `domain_ca_multiturn_messages`, `session_turn_count`)
    │    - `user:*`   : Cross-session persistent user profile & KPI preferences (`user:profile`, `user:preferred_kpis`, `user:pinned_insights`)
    │    - `app:*`    : App-wide query execution counter (`app:total_caa_queries_executed`)
    ├─ Long-Term Memory Management (`ctx.memory_service` + Persistent JSON Backup):
    │    - `before_agent_callback` : `_initialize_session_and_rehydrate_memory` (initializes state & re-hydrates `MemoryService` from `.adk/long_term_memory_bank.json`)
    │    - `after_agent_callback`  : `_save_session_to_long_term_memory` (calls `await callback_context.add_session_to_memory()` & persists to disk)
    │    - Memory Tools            : `preload_memory` (`PreloadMemoryTool`), `load_memory` (`LoadMemoryTool`), `save_user_preference_and_memory`, `inspect_session_and_memory_status`
    │
    ├──> [Sub-Agent 1] `customer_marketing_subagent` (`thelook_customer_marketing_ca`)
    ├──> [Sub-Agent 2] `product_profitability_subagent` (`thelook_product_profitability_ca`)
    └──> [Sub-Agent 3] `supply_chain_logistics_subagent` (`thelook_supply_chain_ca`)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.genai import types

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event
from google.adk.tools import load_memory, preload_memory
from google.adk.tools.data_agent import data_agent_tool
from google.adk.tools.data_agent.config import DataAgentToolConfig
from google.adk.tools.tool_context import ToolContext

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
if PROJECT_ID in ("", "your-gcp-project-id"):
  PROJECT_ID = "ryan-sandbox-agent"

DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
if not DATASET_ID:
  DATASET_ID = "thelook_ecommerce_agent"

# 3 Dedicated Domain-Scoped BigQuery CAA Data Agent IDs
CUSTOMER_MARKETING_CA_ID = "thelook_customer_marketing_ca"
PRODUCT_PROFITABILITY_CA_ID = "thelook_product_profitability_ca"
SUPPLY_CHAIN_CA_ID = "thelook_supply_chain_ca"

CUSTOMER_MARKETING_CA_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/{CUSTOMER_MARKETING_CA_ID}"
)
PRODUCT_PROFITABILITY_CA_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/{PRODUCT_PROFITABILITY_CA_ID}"
)
SUPPLY_CHAIN_CA_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/global/dataAgents/{SUPPLY_CHAIN_CA_ID}"
)

_TOOL_SETTINGS = DataAgentToolConfig(
    max_query_result_rows=30,
    location="global",
)

# Persistent Long-Term Memory Bank file (survives `adk web` server restarts)
_AGENT_DIR = Path(__file__).resolve().parent
_PERSISTENT_MEMORY_FILE = _AGENT_DIR / ".adk" / "long_term_memory_bank.json"

_DEFAULT_USER_PROFILE = {
    "role": "Enterprise Business Analyst",
    "focus_department": "All (Women / Men)",
    "focus_channel": "All Channels",
}
_DEFAULT_PREFERRED_KPIS = [
    "VIP 고객",
    "상품 마진율",
    "취소/반품 비율(환불률)",
    "평균 배송 소요 시간",
]


def _utc_now_iso() -> str:
  return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_persistent_memory_store() -> dict[str, Any]:
  """Loads the local JSON memory bank from `.adk/long_term_memory_bank.json`."""
  if not _PERSISTENT_MEMORY_FILE.exists():
    return {"user_profiles": {}, "sessions": {}, "explicit_memories": []}
  try:
    return json.loads(_PERSISTENT_MEMORY_FILE.read_text(encoding="utf-8"))
  except Exception:
    return {"user_profiles": {}, "sessions": {}, "explicit_memories": []}


def _save_persistent_memory_store(store: dict[str, Any]) -> None:
  """Persists the local JSON memory bank to `.adk/long_term_memory_bank.json`."""
  try:
    _PERSISTENT_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PERSISTENT_MEMORY_FILE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
  except Exception:
    pass


async def _sync_store_into_adk_memory_service(
    inv_ctx: Any,
    app_name: str,
    user_id: str,
    store: dict[str, Any],
) -> None:
  """Synchronizes persisted session history and explicit insights into ADK `MemoryService`."""
  if inv_ctx is None or getattr(inv_ctx, "memory_service", None) is None:
    return

  rehydrated_events: list[Event] = []
  for sess_data in store.get("sessions", {}).values():
    for q_item in sess_data.get("domain_query_history", []):
      summary_txt = (
          f"[과거 도메인 분석 이력] 도메인={q_item.get('domain')} | 질문={q_item.get('query')} | "
          f"SQL={q_item.get('generated_sql')} | 요약={q_item.get('answer_preview')}"
      )
      rehydrated_events.append(
          Event(
              author=q_item.get("caa_agent_id", "domain_caa_subagent"),
              content=types.Content(
                  role="model",
                  parts=[types.Part.from_text(text=summary_txt)],
              ),
          )
      )
    for ev_item in sess_data.get("events", []):
      text = ev_item.get("text", "").strip()
      if text:
        rehydrated_events.append(
            Event(
                author=ev_item.get("author", "thelook_enterprise_root_router"),
                content=types.Content(
                    role=ev_item.get("role", "model"),
                    parts=[types.Part.from_text(text=text)],
                ),
            )
        )

  for mem_item in store.get("explicit_memories", []):
    text = mem_item.get("text", "").strip()
    if text:
      rehydrated_events.append(
          Event(
              author="long_term_memory_bank",
              content=types.Content(
                  role="model",
                  parts=[types.Part.from_text(text=f"[장기 기억 인사이트] {text}")],
              ),
          )
      )

  if rehydrated_events:
    try:
      await inv_ctx.memory_service.add_events_to_memory(
          app_name=app_name,
          user_id=user_id,
          events=rehydrated_events,
          session_id="persisted_long_term_memory",
      )
    except Exception:
      pass


# ==============================================================================
# ADK Lifecycle Callbacks: Session State Init + Long-Term Memory Sync
# ==============================================================================
async def _initialize_session_and_rehydrate_memory(
    callback_context: CallbackContext,
) -> None:
  """`before_agent_callback`: Initializes 4-Scope Session State and re-hydrates `MemoryService`."""
  state = callback_context.state
  session = callback_context.session
  user_id = callback_context.user_id or "default_user"
  app_name = session.app_name or "bq_caa_3domain_multi_agent"

  store = _load_persistent_memory_store()
  persisted_user = store.get("user_profiles", {}).get(user_id, {})

  is_new_session = "session_started_at" not in state

  # 1. Session-Scoped State (persists across turns within the current session)
  if is_new_session:
    state["session_started_at"] = _utc_now_iso()
    state["session_turn_count"] = 0
    state["active_domain"] = "Root Router"
    state["domain_query_history"] = []
    state["domain_ca_multiturn_messages"] = {}

  # 2. User-Scoped State (`user:*` persists across different sessions for the same user)
  if is_new_session or "user:profile" not in state:
    state["user:profile"] = persisted_user.get(
        "profile", dict(_DEFAULT_USER_PROFILE)
    )
  if is_new_session or "user:preferred_kpis" not in state:
    state["user:preferred_kpis"] = persisted_user.get(
        "preferred_kpis", list(_DEFAULT_PREFERRED_KPIS)
    )
  if is_new_session or "user:pinned_insights" not in state:
    state["user:pinned_insights"] = persisted_user.get("pinned_insights", [])

  # 3. App-Scoped State (`app:*` shared across all users/sessions)
  if is_new_session or "app:total_caa_queries_executed" not in state:
    state["app:total_caa_queries_executed"] = store.get(
        "total_caa_queries_executed", 0
    )

  # 4. Sync persisted memories into ADK `MemoryService` (`InMemoryMemoryService`)
  inv_ctx = callback_context._invocation_context  # pylint: disable=protected-access
  await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)


async def _save_session_to_long_term_memory(
    callback_context: CallbackContext,
) -> types.Content | None:
  """`after_agent_callback`: Indexes `ctx.session` into ADK `MemoryService` and persists to disk."""
  session = callback_context.session
  state = callback_context.state
  user_id = callback_context.user_id or "default_user"
  app_name = session.app_name or "bq_caa_3domain_multi_agent"

  # 1. Native ADK Memory Object indexing (`await callback_context.add_session_to_memory()`)
  try:
    await callback_context.add_session_to_memory()
  except Exception:
    pass

  # 2. Merge & persist session events and `user:*` / `app:*` state to `.adk/long_term_memory_bank.json`
  store = _load_persistent_memory_store()
  existing_user = store.get("user_profiles", {}).get(user_id, {})

  cur_profile = state.get("user:profile")
  if cur_profile and cur_profile != _DEFAULT_USER_PROFILE:
    merged_profile = cur_profile
  else:
    merged_profile = existing_user.get("profile") or cur_profile or dict(_DEFAULT_USER_PROFILE)

  cur_kpis = state.get("user:preferred_kpis")
  if cur_kpis and cur_kpis != _DEFAULT_PREFERRED_KPIS:
    merged_kpis = cur_kpis
  else:
    merged_kpis = existing_user.get("preferred_kpis") or cur_kpis or list(_DEFAULT_PREFERRED_KPIS)

  cur_pinned = state.get("user:pinned_insights") or existing_user.get("pinned_insights", [])

  store.setdefault("user_profiles", {})[user_id] = {
      "profile": merged_profile,
      "preferred_kpis": merged_kpis,
      "pinned_insights": cur_pinned,
      "updated_at": _utc_now_iso(),
  }
  store["total_caa_queries_executed"] = max(
      int(store.get("total_caa_queries_executed", 0)),
      int(state.get("app:total_caa_queries_executed", 0)),
  )

  serialized_events: list[dict[str, str]] = []
  for ev in session.events[-30:]:
    if not ev.content or not ev.content.parts:
      continue
    texts = [p.text for p in ev.content.parts if getattr(p, "text", None)]
    joined = "\n".join(texts).strip()
    if joined:
      serialized_events.append({
          "author": ev.author or "agent",
          "role": ev.content.role or "model",
          "text": joined[:2000],
      })

  existing_sess = store.get("sessions", {}).get(session.id, {})
  cur_history = state.get("domain_query_history") or existing_sess.get("domain_query_history", [])

  store.setdefault("sessions", {})[session.id] = {
      "session_id": session.id,
      "user_id": user_id,
      "updated_at": _utc_now_iso(),
      "active_domain": state.get("active_domain") or existing_sess.get("active_domain", "Root Router"),
      "domain_query_history": cur_history[-15:],
      "events": serialized_events or existing_sess.get("events", []),
  }
  _save_persistent_memory_store(store)

  inv_ctx = callback_context._invocation_context  # pylint: disable=protected-access
  await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)
  return None


# ==============================================================================
# BigQuery CAA Helper with Session Multi-Turn History & State Recording
# ==============================================================================
def _get_cloud_platform_adc():
  """Loads Keyless ADC with `cloud-platform` scope and quota project `ryan-sandbox-agent`."""
  creds, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  if hasattr(creds, "with_quota_project"):
    creds = creds.with_quota_project(PROJECT_ID)
  return creds


def _format_markdown_table(rows: list[dict[str, Any]], max_rows: int = 20) -> str:
  """Converts BigQuery result rows into a compact Markdown table (Token Diet)."""
  if not rows:
    return ""
  headers = list(rows[0].keys())
  header_line = "| " + " | ".join(headers) + " |"
  sep_line = "| " + " | ".join("---" for _ in headers) + " |"
  body_lines = [
      "| " + " | ".join(str(r.get(h, "")) for h in headers) + " |"
      for r in rows[:max_rows]
  ]
  footer = (
      f"\n*(Showing top {max_rows} of {len(rows)} rows)*"
      if len(rows) > max_rows
      else f"\n*(Total {len(rows)} rows)*"
  )
  return "\n".join([header_line, sep_line, *body_lines]) + footer


def _record_caa_result_into_session_state(
    state: Any,
    agent_id: str,
    domain_label: str,
    data_agent_name: str,
    query: str,
    generated_sql: str,
    rows: list[dict[str, Any]],
    ca_final_answer: str,
    session_id: str = "active_session",
    user_id: str = "default_user",
) -> None:
  """Updates all 4 ADK Session State scopes (`temp:`, `session`, `user:`, `app:`) and disk store."""
  # 1. `temp:*` (Turn / Invocation Scope)
  state["temp:last_caa_domain"] = domain_label
  state["temp:last_caa_agent"] = data_agent_name
  state["temp:last_caa_sql"] = generated_sql
  state["temp:last_caa_row_count"] = len(rows)
  state["temp:last_caa_rows"] = rows[:20]

  # 2. Session Scope (Multi-Turn History within current session)
  turn_num = int(state.get("session_turn_count", 0)) + 1
  state["session_turn_count"] = turn_num
  state["active_domain"] = domain_label

  history_entry = {
      "turn": turn_num,
      "timestamp": _utc_now_iso(),
      "domain": domain_label,
      "caa_agent_id": agent_id,
      "query": query,
      "generated_sql": generated_sql,
      "row_count": len(rows),
      "answer_preview": ca_final_answer[:300],
  }
  history = list(state.get("domain_query_history", []))
  history.append(history_entry)
  state["domain_query_history"] = history[-20:]

  # Store multi-turn messages per domain CAA agent for context chaining
  multiturn_map = dict(state.get("domain_ca_multiturn_messages", {}))
  agent_msgs = list(multiturn_map.get(agent_id, []))
  agent_msgs.append({"userMessage": {"text": query}})
  sys_summary = ca_final_answer or f"Executed SQL:\n{generated_sql}"
  agent_msgs.append({"systemMessage": {"text": {"parts": [sys_summary[:1000]]}}})
  multiturn_map[agent_id] = agent_msgs[-6:]  # Keep last 3 turns (6 messages)
  state["domain_ca_multiturn_messages"] = multiturn_map

  # 3. App Scope (`app:*`)
  store = _load_persistent_memory_store()
  new_total = max(
      int(store.get("total_caa_queries_executed", 0)),
      int(state.get("app:total_caa_queries_executed", 0)),
  ) + 1
  state["app:total_caa_queries_executed"] = new_total
  store["total_caa_queries_executed"] = new_total

  sess_entry = store.setdefault("sessions", {}).setdefault(
      session_id,
      {"session_id": session_id, "user_id": user_id, "domain_query_history": [], "events": []},
  )
  sess_entry["updated_at"] = _utc_now_iso()
  sess_entry["active_domain"] = domain_label
  sess_entry["domain_query_history"] = state["domain_query_history"][-15:]
  _save_persistent_memory_store(store)


def _query_domain_caa_agent(
    agent_id: str,
    domain_label: str,
    query: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Calls a specific domain-scoped BigQuery CAA Data Agent directly via `:chat` with Multi-Turn Session History."""
  data_agent_name = f"projects/{PROJECT_ID}/locations/global/dataAgents/{agent_id}"
  session = AuthorizedSession(_get_cloud_platform_adc())
  url = f"https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/global:chat"

  # Chain previous domain conversation turns from `tool_context.state` if available
  messages: list[dict[str, Any]] = []
  if tool_context is not None:
    multiturn_map = tool_context.state.get("domain_ca_multiturn_messages", {})
    if isinstance(multiturn_map, dict) and agent_id in multiturn_map:
      messages.extend(multiturn_map[agent_id][-4:])
  messages.append({"userMessage": {"text": query}})

  payload = {
      "messages": messages,
      "dataAgentContext": {"dataAgent": data_agent_name},
      "clientIdEnum": "GOOGLE_ADK",
  }
  headers = {
      "Content-Type": "application/json",
      "X-Goog-API-Client": "GOOGLE_ADK",
  }

  chunks: list[dict[str, Any]] = []
  accumulator = ""
  try:
    with session.post(url, json=payload, headers=headers, stream=True, timeout=120) as resp:
      if not resp.ok:
        return {
            "status": "ERROR",
            "domain": domain_label,
            "data_agent": data_agent_name,
            "error_details": f"HTTP {resp.status_code}: {resp.text}",
        }
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
  except Exception as exc:
    return {
        "status": "ERROR",
        "domain": domain_label,
        "data_agent": data_agent_name,
        "error_details": str(exc),
    }

  thoughts: list[str] = []
  final_texts: list[str] = []
  generated_sql = ""
  rows: list[dict[str, Any]] = []

  for item in chunks:
    sm = item.get("systemMessage", {})
    if not isinstance(sm, dict):
      continue
    if "text" in sm and isinstance(sm["text"], dict):
      parts = sm["text"].get("parts", [])
      text_type = sm["text"].get("textType", "")
      joined = "".join(str(p) for p in parts).strip()
      if joined:
        if text_type == "THOUGHT":
          thoughts.append(joined)
        else:
          final_texts.append(joined)
    if "data" in sm and isinstance(sm["data"], dict):
      data_obj = sm["data"]
      if data_obj.get("generatedSql"):
        generated_sql = data_obj["generatedSql"].strip()
      res_obj = data_obj.get("result")
      if isinstance(res_obj, dict) and isinstance(res_obj.get("data"), list):
        rows = res_obj["data"]

  markdown_table = _format_markdown_table(rows, max_rows=20)
  ca_final_answer = "\n\n".join(final_texts).strip()

  if tool_context is not None:
    _record_caa_result_into_session_state(
        state=tool_context.state,
        agent_id=agent_id,
        domain_label=domain_label,
        data_agent_name=data_agent_name,
        query=query,
        generated_sql=generated_sql,
        rows=rows,
        ca_final_answer=ca_final_answer,
        session_id=tool_context.session.id,
        user_id=tool_context.user_id or "default_user",
    )

  return {
      "status": "SUCCESS",
      "domain": domain_label,
      "data_agent": data_agent_name,
      "query": query,
      "multiturn_context_messages_sent": len(messages),
      "generated_sql": generated_sql,
      "row_count": len(rows),
      "markdown_table": markdown_table,
      "ca_final_answer": ca_final_answer,
      "thought_summary": thoughts[-1] if thoughts else "",
  }


# ==============================================================================
# Session & Long-Term Memory Management Tools (Exposed to Root & Sub-Agents)
# ==============================================================================
async def save_user_preference_and_memory(
    role: str = "",
    focus_department: str = "",
    focus_channel: str = "",
    preferred_kpis_csv: str = "",
    key_insight_to_remember: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Saves user analysis preferences (`user:*` state) and explicit long-term business insights (`MemoryService`).

  Call this tool when the user states their role, preferred department/channel/KPIs, or asks to
  remember a specific analytical finding across future sessions.

  Args:
      role: User's job title or role (e.g., 'MD 본부장', '마케팅 팀장', 'SCM 총괄').
      focus_department: Preferred department filter (e.g., 'Women', 'Men').
      focus_channel: Preferred marketing channel filter (e.g., 'Search', 'Email').
      preferred_kpis_csv: Comma-separated KPIs of interest (e.g., 'VIP 고객, 상품 마진율, 환불률').
      key_insight_to_remember: Important analytical finding or business rule to remember across sessions.
  """
  if tool_context is None:
    return {"status": "ERROR", "message": "ToolContext is required."}

  state = tool_context.state
  user_id = tool_context.user_id or "default_user"
  app_name = tool_context.session.app_name or "bq_caa_3domain_multi_agent"

  store = _load_persistent_memory_store()
  existing_user = store.get("user_profiles", {}).get(user_id, {})

  profile = dict(
      state.get("user:profile")
      or existing_user.get("profile")
      or _DEFAULT_USER_PROFILE
  )
  if role.strip():
    profile["role"] = role.strip()
  if focus_department.strip():
    profile["focus_department"] = focus_department.strip()
  if focus_channel.strip():
    profile["focus_channel"] = focus_channel.strip()
  state["user:profile"] = profile

  if preferred_kpis_csv.strip():
    kpis = [k.strip() for k in preferred_kpis_csv.split(",") if k.strip()]
    if kpis:
      state["user:preferred_kpis"] = kpis

  pinned = list(
      state.get("user:pinned_insights")
      or existing_user.get("pinned_insights", [])
  )
  memory_summary_parts = [
      f"[사용자 프로필/선호 설정] 역할={profile.get('role')}, 관심부서={profile.get('focus_department')}, "
      f"관심채널={profile.get('focus_channel')}, 핵심KPI={state.get('user:preferred_kpis')}"
  ]

  if key_insight_to_remember.strip():
    entry = {
        "timestamp": _utc_now_iso(),
        "insight": key_insight_to_remember.strip(),
    }
    pinned.append(entry)
    state["user:pinned_insights"] = pinned[-20:]
    memory_summary_parts.append(f"[핵심 분석 인사이트 기억] {key_insight_to_remember.strip()}")

  memory_text = " | ".join(memory_summary_parts)

  # Persist to local JSON store and index into ADK MemoryService immediately
  store.setdefault("user_profiles", {})[user_id] = {
      "profile": state["user:profile"],
      "preferred_kpis": state.get("user:preferred_kpis", []),
      "pinned_insights": state.get("user:pinned_insights", []),
      "updated_at": _utc_now_iso(),
  }
  store.setdefault("explicit_memories", []).append({
      "timestamp": _utc_now_iso(),
      "user_id": user_id,
      "text": memory_text,
  })
  _save_persistent_memory_store(store)

  inv_ctx = tool_context._invocation_context  # pylint: disable=protected-access
  await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)

  return {
      "status": "SUCCESS",
      "updated_user_profile": state["user:profile"],
      "updated_preferred_kpis": state.get("user:preferred_kpis", []),
      "pinned_insights_count": len(state.get("user:pinned_insights", [])),
      "indexed_to_memory_service": memory_text,
  }


async def inspect_session_and_memory_status(
    memory_search_query: str = "VIP 마진율 환불률 물류 배송",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Inspects the current ADK `Session` object (4-Scope State & Events) and `Memory` object (`search_memory`).

  Call this tool when the user asks to verify or inspect Session State (`temp:`, `session`, `user:`, `app:`)
  or Long-Term Memory (`MemoryService` / past sessions).

  Args:
      memory_search_query: Keyword query to test retrieving past memories from ADK `MemoryService`.
  """
  if tool_context is None:
    return {"status": "ERROR", "message": "ToolContext is required."}

  session = tool_context.session
  state = tool_context.state
  user_id = tool_context.user_id or "default_user"
  app_name = session.app_name or "bq_caa_3domain_multi_agent"

  store = _load_persistent_memory_store()
  inv_ctx = tool_context._invocation_context  # pylint: disable=protected-access
  await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)

  # Search ADK MemoryService
  matched_memories: list[dict[str, str]] = []
  try:
    mem_resp = await tool_context.search_memory(memory_search_query)
    for m in mem_resp.memories[:10]:
      parts_text = " ".join(
          p.text for p in (m.content.parts if m.content and m.content.parts else []) if getattr(p, "text", None)
      )
      matched_memories.append({
          "author": m.author or "agent",
          "timestamp": m.timestamp or "",
          "text_preview": parts_text[:300],
      })
  except Exception as exc:
    matched_memories.append({"error": str(exc)})

  return {
      "status": "SUCCESS",
      "session_object": {
          "session_id": session.id,
          "app_name": session.app_name,
          "user_id": session.user_id,
          "total_events_in_current_session": len(session.events),
          "session_started_at": state.get("session_started_at"),
          "session_turn_count": state.get("session_turn_count", 0),
          "active_domain": state.get("active_domain", "Root Router"),
      },
      "state_scopes": {
          "1_temp_scope (current turn only)": {
              "temp:last_caa_domain": state.get("temp:last_caa_domain"),
              "temp:last_caa_agent": state.get("temp:last_caa_agent"),
              "temp:last_caa_row_count": state.get("temp:last_caa_row_count"),
              "temp:last_caa_sql_present": bool(state.get("temp:last_caa_sql")),
          },
          "2_session_scope (multi-turn within session)": {
              "domain_query_history_count": len(state.get("domain_query_history", [])),
              "domain_query_history": state.get("domain_query_history", [])[-5:],
              "tracked_multiturn_caa_agents": list(
                  state.get("domain_ca_multiturn_messages", {}).keys()
              ),
          },
          "3_user_scope (persists across all sessions for user)": {
              "user:profile": state.get("user:profile"),
              "user:preferred_kpis": state.get("user:preferred_kpis"),
              "user:pinned_insights": state.get("user:pinned_insights"),
          },
          "4_app_scope (global across app)": {
              "app:total_caa_queries_executed": state.get(
                  "app:total_caa_queries_executed", 0
              ),
          },
      },
      "memory_object_long_term": {
          "memory_search_query": memory_search_query,
          "in_memory_service_matches_count": len(matched_memories),
          "in_memory_service_matches": matched_memories[:5],
          "persistent_disk_sessions_saved": len(store.get("sessions", {})),
          "persistent_explicit_memories_saved": len(
              store.get("explicit_memories", [])
          ),
          "persistent_file_path": str(_PERSISTENT_MEMORY_FILE),
      },
  }


# ==============================================================================
# Sub-Agent 1 Tools: Customer CRM & Marketing Funnel (`thelook_customer_marketing_ca`)
# ==============================================================================
def ask_customer_marketing_caa(
    query: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Queries BigQuery CAA Sub-Agent #1 (`thelook_customer_marketing_ca`) for Customer & Marketing analytics.

  Target Tables: `users`, `events`, `orders`, `order_items`
  Domain KPIs: VIP 고객, 이탈/휴면 고객, 신규 가입 고객, 유입 경로(traffic_source), 장바구니 포기율(이탈율), 객단가(AOV)/ARPU.

  Args:
      query: Standalone natural-language analytical question in Korean or English.
  """
  return _query_domain_caa_agent(
      agent_id=CUSTOMER_MARKETING_CA_ID,
      domain_label="Domain 1: Customer CRM & Marketing Funnel",
      query=query,
      tool_context=tool_context,
  )


def get_customer_marketing_caa_info() -> dict[str, Any]:
  """Returns metadata, connected BigQuery tables, and system instruction of `thelook_customer_marketing_ca`."""
  return data_agent_tool.get_data_agent_info(
      data_agent_name=CUSTOMER_MARKETING_CA_RESOURCE,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
  )


# ==============================================================================
# Sub-Agent 2 Tools: Product, Margin & Return Analytics (`thelook_product_profitability_ca`)
# ==============================================================================
def ask_product_profitability_caa(
    query: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Queries BigQuery CAA Sub-Agent #2 (`thelook_product_profitability_ca`) for Product, Margin & Return analytics.

  Target Tables: `products`, `order_items`, `orders`
  Domain KPIs: 상품 마진율, 실판매 마진액/순매출액, 반품/취소 건, 취소/반품 비율(환불률), 부서/카테고리/브랜드 수익성.

  Args:
      query: Standalone natural-language analytical question in Korean or English.
  """
  return _query_domain_caa_agent(
      agent_id=PRODUCT_PROFITABILITY_CA_ID,
      domain_label="Domain 2: Product, Profitability & Return Analytics",
      query=query,
      tool_context=tool_context,
  )


def get_product_profitability_caa_info() -> dict[str, Any]:
  """Returns metadata, connected BigQuery tables, and system instruction of `thelook_product_profitability_ca`."""
  return data_agent_tool.get_data_agent_info(
      data_agent_name=PRODUCT_PROFITABILITY_CA_RESOURCE,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
  )


# ==============================================================================
# Sub-Agent 3 Tools: Supply Chain, Inventory & Logistics (`thelook_supply_chain_ca`)
# ==============================================================================
def ask_supply_chain_logistics_caa(
    query: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Queries BigQuery CAA Sub-Agent #3 (`thelook_supply_chain_ca`) for Supply Chain, Inventory & Fulfillment analytics.

  Target Tables: `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`
  Domain KPIs: 물류 센터(DC/창고), 평균 배송 소요 시간(배송 리드타임), 출고 준비 리드타임, 미판매 재고율(sold_at IS NULL), 재고 원가 총액.

  Args:
      query: Standalone natural-language analytical question in Korean or English.
  """
  return _query_domain_caa_agent(
      agent_id=SUPPLY_CHAIN_CA_ID,
      domain_label="Domain 3: Supply Chain, Inventory & Logistics",
      query=query,
      tool_context=tool_context,
  )


def get_supply_chain_logistics_caa_info() -> dict[str, Any]:
  """Returns metadata, connected BigQuery tables, and system instruction of `thelook_supply_chain_ca`."""
  return data_agent_tool.get_data_agent_info(
      data_agent_name=SUPPLY_CHAIN_CA_RESOURCE,
      credentials=_get_cloud_platform_adc(),
      settings=_TOOL_SETTINGS,
  )


# ==============================================================================
# Root Router Tools: Architecture Registry & Parallel Cross-Domain Synthesis
# ==============================================================================
def list_domain_caa_registry() -> dict[str, Any]:
  """Returns the 3 Domain-Scoped BigQuery CAA Sub-Agents registry, mapped tables, and Business Glossary KPIs."""
  return {
      "project_id": PROJECT_ID,
      "dataset": f"{PROJECT_ID}.{DATASET_ID}",
      "architecture": "Hierarchical Root Router + 3 Domain-Scoped BigQuery CAA Sub-Agents (with Session & Memory Bank)",
      "sub_agents": [
          {
              "sub_agent_name": "customer_marketing_subagent",
              "caa_data_agent": CUSTOMER_MARKETING_CA_RESOURCE,
              "domain": "고객 CRM & 마케팅 퍼널 분석 (Customer & Marketing)",
              "tables": ["users", "events", "orders", "order_items"],
              "business_glossary_kpis": [
                  "VIP 고객 (누적 구매액 >= $500 OR 주문건수 >= 5회)",
                  "이탈/휴면 고객 (최근 90일 이내 무주문)",
                  "신규 가입 고객 (최근 30일 이내 가입)",
                  "유입 경로 (users.traffic_source)",
                  "장바구니 포기율 (cart 세션 중 미구매 비율 %)",
                  "객단가 (AOV) 및 인당 평균 매출 (ARPU)",
              ],
          },
          {
              "sub_agent_name": "product_profitability_subagent",
              "caa_data_agent": PRODUCT_PROFITABILITY_CA_RESOURCE,
              "domain": "상품·카테고리 수익성 & 반품 분석 (Product & Profitability)",
              "tables": ["products", "order_items", "orders"],
              "business_glossary_kpis": [
                  "상품 마진율 ((retail_price - cost) / retail_price * 100)",
                  "실판매 마진액 (Realized Gross Profit) 및 순매출액 (Net Revenue)",
                  "반품/취소 건 (status IN ('Returned', 'Cancelled'))",
                  "취소/반품 비율 (환불률 %)",
                  "부서(department) / 카테고리(category) / 브랜드(brand) 수익성",
              ],
          },
          {
              "sub_agent_name": "supply_chain_logistics_subagent",
              "caa_data_agent": SUPPLY_CHAIN_CA_RESOURCE,
              "domain": "물류 센터·재고·배송 리드타임 분석 (Supply Chain & Logistics)",
              "tables": [
                  "distribution_centers",
                  "inventory_items",
                  "order_items",
                  "orders",
                  "products",
              ],
              "business_glossary_kpis": [
                  "물류 센터 (distribution_centers / 창고 / DC)",
                  "평균 배송 소요 시간 (TIMESTAMP_DIFF(delivered_at, shipped_at, DAY/HOUR))",
                  "출고 준비 리드타임 (TIMESTAMP_DIFF(shipped_at, created_at, HOUR))",
                  "미판매 재고율 (inventory_items.sold_at IS NULL 비율 %)",
                  "미판매 재고 원가 총액 (SUM(cost) WHERE sold_at IS NULL)",
              ],
          },
      ],
  }


def run_cross_domain_caa_analysis(
    customer_marketing_query: str = "",
    product_profitability_query: str = "",
    supply_chain_logistics_query: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
  """Executes multiple domain-scoped BigQuery CAA Data Agents in parallel for cross-domain composite questions.

  Use this tool ONLY when the user's question spans 2 or more domains simultaneously
  (e.g., asking for Customer VIP metrics + Product Margin/Refund metrics + Logistics DC Delivery metrics together).
  Leave a domain's query empty (`""`) if that domain is not needed.

  Args:
      customer_marketing_query: Question for `thelook_customer_marketing_ca` (or empty string).
      product_profitability_query: Question for `thelook_product_profitability_ca` (or empty string).
      supply_chain_logistics_query: Question for `thelook_supply_chain_ca` (or empty string).
  """
  tasks: list[tuple[str, str, str]] = []
  if customer_marketing_query.strip():
    tasks.append((
        CUSTOMER_MARKETING_CA_ID,
        "Domain 1: Customer CRM & Marketing Funnel",
        customer_marketing_query.strip(),
    ))
  if product_profitability_query.strip():
    tasks.append((
        PRODUCT_PROFITABILITY_CA_ID,
        "Domain 2: Product, Profitability & Return Analytics",
        product_profitability_query.strip(),
    ))
  if supply_chain_logistics_query.strip():
    tasks.append((
        SUPPLY_CHAIN_CA_ID,
        "Domain 3: Supply Chain, Inventory & Logistics",
        supply_chain_logistics_query.strip(),
    ))

  if not tasks:
    return {"status": "NO_QUERIES_PROVIDED"}

  results: dict[str, Any] = {}
  with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
    future_map = {
        pool.submit(_query_domain_caa_agent, agent_id, label, q, None): (
            agent_id,
            label,
            q,
        )
        for agent_id, label, q in tasks
    }
    for fut, (agent_id, label, q) in future_map.items():
      res = fut.result()
      results[label] = res
      if tool_context is not None and res.get("status") == "SUCCESS":
        _record_caa_result_into_session_state(
            state=tool_context.state,
            agent_id=agent_id,
            domain_label=f"Cross-Domain ({label})",
            data_agent_name=res.get("data_agent", ""),
            query=q,
            generated_sql=res.get("generated_sql", ""),
            rows=[],
            ca_final_answer=res.get("ca_final_answer", ""),
            session_id=tool_context.session.id,
            user_id=tool_context.user_id or "default_user",
        )

  return {
      "status": "SUCCESS",
      "executed_domains": len(tasks),
      "domain_results": results,
  }


_SHARED_SESSION_MEMORY_CONTEXT = """
### [현재 ADK Session State 및 사용자 장기 기억 컨텍스트]
- **사용자 프로필 (`user:profile`)**: {user:profile?}
- **사용자 중점 관리 KPI (`user:preferred_kpis`)**: {user:preferred_kpis?}
- **저장된 핵심 인사이트 (`user:pinned_insights`)**: {user:pinned_insights?}
- **현재 세션 누적 분석 턴 수 (`session_turn_count`)**: {session_turn_count?}
- **최근 도메인 분석 이력 (`domain_query_history`)**: {domain_query_history?}
"""


# ==============================================================================
# 3 Domain-Scoped ADK Sub-Agents
# ==============================================================================
customer_marketing_subagent = LlmAgent(
    model="gemini-2.5-flash",
    name="customer_marketing_subagent",
    description=(
        "Sub-Agent #1 for Customer CRM & Marketing Funnel analytics via BigQuery CAA "
        f"(`{CUSTOMER_MARKETING_CA_ID}`). Handles VIP customers, churn/dormant users, new signups, "
        "traffic_source performance, cart abandonment rate, AOV, and ARPU on `users`, `events`, `orders`, `order_items`."
    ),
    instruction=(
        "당신은 **고객 CRM 및 마케팅 퍼널 분석 전담 서브 에이전트(`customer_marketing_subagent`)**입니다.\n"
        f"- 전담 BigQuery CAA 리소스: `{CUSTOMER_MARKETING_CA_RESOURCE}`\n"
        "- 연결된 테이블 (4개): `users`, `events`, `orders`, `order_items`\n"
        "- 담당 핵심 지표: VIP 고객(우수 고객), 이탈/휴면 고객, 신규 가입 고객, 유입 경로(`traffic_source`), 장바구니 포기율(이탈율), 객단가(AOV), ARPU\n"
        + _SHARED_SESSION_MEMORY_CONTEXT
        + "\n[수행 지침]\n"
        "1. 고객/마케팅 관련 데이터 질문이 들어오면 반드시 `ask_customer_marketing_caa(query=...)` 도구를 호출하세요.\n"
        "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 구체적인 조건으로 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
        "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
        "3. 만약 사용자의 후속 질문이 **상품 마진율/반품/카테고리 수익성** 도메인이라면 `product_profitability_subagent`로 제어권을 이관(`transfer_to_agent`)하고, "
        "**물류센터/배송 소요 시간/미판매 재고** 도메인이라면 `supply_chain_logistics_subagent`로 이관하며, "
        "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
        "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) 마케팅 비즈니스 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
    ),
    tools=[
        preload_memory,
        load_memory,
        ask_customer_marketing_caa,
        get_customer_marketing_caa_info,
        save_user_preference_and_memory,
        inspect_session_and_memory_status,
    ],
    before_agent_callback=_initialize_session_and_rehydrate_memory,
    after_agent_callback=_save_session_to_long_term_memory,
)

product_profitability_subagent = LlmAgent(
    model="gemini-2.5-flash",
    name="product_profitability_subagent",
    description=(
        "Sub-Agent #2 for Product Merchandising, Gross Margin & Return/Refund analytics via BigQuery CAA "
        f"(`{PRODUCT_PROFITABILITY_CA_ID}`). Handles product margin %, net revenue, realized gross profit, "
        "return/cancellation rates (환불률), and category/brand/department profitability on `products`, `order_items`, `orders`."
    ),
    instruction=(
        "당신은 **상품·카테고리 수익성 및 반품 분석 전담 서브 에이전트(`product_profitability_subagent`)**입니다.\n"
        f"- 전담 BigQuery CAA 리소스: `{PRODUCT_PROFITABILITY_CA_RESOURCE}`\n"
        "- 연결된 테이블 (3개): `products`, `order_items`, `orders`\n"
        "- 담당 핵심 지표: 상품 마진율(`(retail_price - cost)/retail_price * 100`), 순매출액(Net Revenue), 실판매 마진액(Gross Profit), 반품/취소 건, 취소/반품 비율(환불률), 카테고리/브랜드/부서별 수익성\n"
        + _SHARED_SESSION_MEMORY_CONTEXT
        + "\n[수행 지침]\n"
        "1. 상품/마진/환불/카테고리 매출 관련 질문이 들어오면 반드시 `ask_product_profitability_caa(query=...)` 도구를 호출하세요.\n"
        "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
        "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
        "3. 만약 사용자의 후속 질문이 **고객 세그먼트(VIP/휴면)/유입 경로/장바구니 이탈율** 도메인이라면 `customer_marketing_subagent`로 이관(`transfer_to_agent`)하고, "
        "**물류센터/배송 소요 시간/미판매 재고** 도메인이라면 `supply_chain_logistics_subagent`로 이관하며, "
        "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
        "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) 상품/수익성 MD 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
    ),
    tools=[
        preload_memory,
        load_memory,
        ask_product_profitability_caa,
        get_product_profitability_caa_info,
        save_user_preference_and_memory,
        inspect_session_and_memory_status,
    ],
    before_agent_callback=_initialize_session_and_rehydrate_memory,
    after_agent_callback=_save_session_to_long_term_memory,
)

supply_chain_logistics_subagent = LlmAgent(
    model="gemini-2.5-flash",
    name="supply_chain_logistics_subagent",
    description=(
        "Sub-Agent #3 for Supply Chain, Inventory & Fulfillment Lead-Time analytics via BigQuery CAA "
        f"(`{SUPPLY_CHAIN_CA_ID}`). Handles distribution centers (물류센터/DC), average delivery lead time (평균 배송 소요 시간), "
        "order-to-ship time, unsold inventory rate (미판매 재고율), and inventory holding cost on "
        "`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`."
    ),
    instruction=(
        "당신은 **물류·재고·배송 리드타임(SCM) 분석 전담 서브 에이전트(`supply_chain_logistics_subagent`)**입니다.\n"
        f"- 전담 BigQuery CAA 리소스: `{SUPPLY_CHAIN_CA_RESOURCE}`\n"
        "- 연결된 테이블 (5개): `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`\n"
        "- 담당 핵심 지표: 물류 센터(창고/DC), 평균 배송 소요 시간(`TIMESTAMP_DIFF(delivered_at, shipped_at, DAY)`), 출고 준비 리드타임, 미판매 재고율(`sold_at IS NULL`), 미판매 재고 원가 총액\n"
        + _SHARED_SESSION_MEMORY_CONTEXT
        + "\n[수행 지침]\n"
        "1. 물류센터/배송 리드타임/재고 관련 질문이 들어오면 반드시 `ask_supply_chain_logistics_caa(query=...)` 도구를 호출하세요.\n"
        "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
        "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
        "3. 만약 사용자의 후속 질문이 **고객(VIP/휴면)/유입 경로/장바구니 퍼널** 도메인이라면 `customer_marketing_subagent`로 이관(`transfer_to_agent`)하고, "
        "**상품 마진율/반품/카테고리 수익성** 도메인이라면 `product_profitability_subagent`로 이관하며, "
        "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
        "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) SCM/물류 최적화 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
    ),
    tools=[
        preload_memory,
        load_memory,
        ask_supply_chain_logistics_caa,
        get_supply_chain_logistics_caa_info,
        save_user_preference_and_memory,
        inspect_session_and_memory_status,
    ],
    before_agent_callback=_initialize_session_and_rehydrate_memory,
    after_agent_callback=_save_session_to_long_term_memory,
)


# ==============================================================================
# Root Agent: Enterprise Multi-Domain Router & Session/Memory Orchestrator
# ==============================================================================
root_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="thelook_enterprise_root_router",
    description=(
        "Enterprise Root Router Agent orchestrating 3 Domain-Scoped BigQuery CAA Sub-Agents "
        "(`customer_marketing_subagent`, `product_profitability_subagent`, `supply_chain_logistics_subagent`) "
        f"with 4-Scope Session State and Long-Term Memory Bank on `{PROJECT_ID}.{DATASET_ID}`."
    ),
    instruction=(
        f"당신은 `{PROJECT_ID}.{DATASET_ID}` 데이터 레이크의 **엔터프라이즈 멀티 에이전트 루트 라우터(`thelook_enterprise_root_router`)**입니다.\n"
        "하위에 도메인별로 테이블 범위(Table Scope)와 비즈니스 용어집(Business Glossary)이 분리된 **3개의 BigQuery CAA 전문 서브 에이전트(Sub-Agents)**를 거느리고 있으며, "
        "**ADK Session Object(4-Scope State + Multi-Turn History)** 및 **ADK Memory Object(세션 간 장기 기억)**를 통합 관리합니다.\n"
        + _SHARED_SESSION_MEMORY_CONTEXT
        + "\n### [하위 3대 BigQuery CAA 서브 에이전트 구성]\n"
        "1. **`customer_marketing_subagent` (고객 CRM & 마케팅 퍼널)**\n"
        f"   - BQ CAA 에이전트: `{CUSTOMER_MARKETING_CA_RESOURCE}`\n"
        "   - 담당 테이블: `users`, `events`, `orders`, `order_items`\n"
        "   - 핵심 질문: VIP/우수 고객, 이탈/휴면 고객, 신규 가입 고객, 유입 경로(`traffic_source`), 장바구니 포기율(이탈율), 객단가(AOV)\n"
        "2. **`product_profitability_subagent` (상품·카테고리 수익성 & 반품)**\n"
        f"   - BQ CAA 에이전트: `{PRODUCT_PROFITABILITY_CA_RESOURCE}`\n"
        "   - 담당 테이블: `products`, `order_items`, `orders`\n"
        "   - 핵심 질문: 상품 마진율, 순매출액/실판매 마진액, 반품/취소 건, 취소/반품 비율(환불률), 카테고리/브랜드/부서별 수익성\n"
        "3. **`supply_chain_logistics_subagent` (물류 센터·재고·배송 리드타임)**\n"
        f"   - BQ CAA 에이전트: `{SUPPLY_CHAIN_CA_RESOURCE}`\n"
        "   - 담당 테이블: `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`\n"
        "   - 핵심 질문: 물류 센터(DC/창고)별 성과, 평균 배송 소요 시간(리드타임), 출고 소요일, 미판매 재고율(`sold_at IS NULL`), 재고 원가 총액\n\n"
        "### [라우팅 및 세션/메모리 관리 규칙]\n"
        "1. **사용자 선호도 설정 / 인사이트 기억 요청**:\n"
        "   - 사용자가 본인의 역할/직무, 관심 부서(예: `Women`), 관심 채널, 중점 관리 KPI를 알려주거나 특정 분석 결과를 기억해 달라고 요청하면 `save_user_preference_and_memory(...)` 도구를 호출하여 `user:*` State와 장기 기억(`MemoryService`)에 저장하세요.\n"
        "2. **세션 상태(`Session`) 및 장기 기억(`Memory`) 점검/복원 요청**:\n"
        "   - 사용자가 '현재 세션 상태와 메모리 상태를 보여줘' 또는 '지난 세션에서 내가 어떤 분석을 했었지?'라고 물으면 `inspect_session_and_memory_status(...)` 및 `load_memory(...)` 도구를 호출하여 4단계 State 스코프(`temp:`, `session`, `user:`, `app:`)와 장기 기억 검색 결과를 상세히 브리핑하세요.\n"
        "3. **아키텍처/에이전트 구성 확인 질문**:\n"
        "   - `list_domain_caa_registry()`를 호출하여 3개 서브 에이전트의 도메인·테이블·용어집 구성을 표로 설명하세요.\n"
        "4. **단일 도메인 질문 (Single-Domain Routing)**:\n"
        "   - 고객/마케팅/트래픽/장바구니 → `customer_marketing_subagent`로 `transfer_to_agent` 호출\n"
        "   - 상품/마진/환불률/카테고리/브랜드 → `product_profitability_subagent`로 `transfer_to_agent` 호출\n"
        "   - 물류센터/배송시간/재고 → `supply_chain_logistics_subagent`로 `transfer_to_agent` 호출\n"
        "5. **복합 도메인 질문 (Cross-Domain Executive Query)**:\n"
        "   - 한 질문 안에 2개 이상의 도메인 지표가 동시에 포함된 경우 `run_cross_domain_caa_analysis(...)` 도구를 호출하여 병렬 실행 후 종합 리포트를 작성하세요."
    ),
    sub_agents=[
        customer_marketing_subagent,
        product_profitability_subagent,
        supply_chain_logistics_subagent,
    ],
    tools=[
        preload_memory,
        load_memory,
        list_domain_caa_registry,
        run_cross_domain_caa_analysis,
        save_user_preference_and_memory,
        inspect_session_and_memory_status,
    ],
    before_agent_callback=_initialize_session_and_rehydrate_memory,
    after_agent_callback=_save_session_to_long_term_memory,
)
