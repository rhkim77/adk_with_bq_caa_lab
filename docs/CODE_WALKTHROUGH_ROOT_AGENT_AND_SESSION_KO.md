# [Code Walkthrough Guide] Root Agent & 3 Sub-Agents Python Source Code Line-by-Line 상세 해설서
**Target File**: [`bq_caa_3domain_multi_agent/agent.py`](../bq_caa_3domain_multi_agent/agent.py) (`L1 ~ L1119` 전체 Line-by-Line 분석)

본 문서는 Google ADK 기반 Multi-Agent Main 구현체인 [`bq_caa_3domain_multi_agent/agent.py`](../bq_caa_3domain_multi_agent/agent.py)의 전체 Source Code(`L1 ~ L1119`)를 **단 한 줄의 생략(`...`) 없이 100% 원문 그대로 수록하고 Line-by-Line으로 해부**하여, 각 Line이 **어떤 역할을 수행하는지**, **왜 그렇게 설계되었는지(Design Rationale)**, 그리고 **ADK Runtime(`Runner`, `Session`, `MemoryService`) 및 BigQuery CAA(`:chat` API)와 내부적으로 어떻게 상호작용하는지**를 상세히 설명합니다.

---

## 🧭 전체 Source Code (`L1 ~ L1119`) 구조 요약 Map

| Section | Line 범위 | 핵심 Symbol (Variable / Function / Agent) | 주요 역할 요약 |
| :--- | :--- | :--- | :--- |
| **Part 1** | `L1–L43` | Module Docstring & Standard/ADK Imports | Architecture 개요 정의 및 Google Auth, GenAI, ADK(`LlmAgent`, `CallbackContext`, `Event`, `ToolContext`, `preload_memory`, `load_memory`) Module Import |
| **Part 2** | `L44–L87` | Global Constants (`PROJECT_ID`, `DATASET_ID`, `*_CA_RESOURCE`, `_TOOL_SETTINGS`, `_PERSISTENT_MEMORY_FILE`) | GCP Project/Dataset Environment Variable Binding, 3대 Domain BQ CAA Resource URI 조합, Local JSON Memory Bank 경로 및 기본 User Profile 상수 선언 |
| **Part 3** | `L89–L177` | Persistent Memory Store Helpers (`_utc_now_iso`, `_load_persistent_memory_store`, `_save_persistent_memory_store`, `_sync_store_into_adk_memory_service`) | `.adk/long_term_memory_bank.json` Disk Read/Write 및 저장된 과거 이력·Insight를 ADK `Event` Object로 변환해 `MemoryService.add_events_to_memory()`에 동기화 |
| **Part 4** | `L179–L300` | ADK Lifecycle Callbacks (`_initialize_session_and_rehydrate_memory`, `_save_session_to_long_term_memory`) | 매 Turn 시작 전(`before_agent_callback`) 4-Scope `Session.state` 초기화/복원 및 매 Turn 종료 후(`after_agent_callback`) `add_session_to_memory()` 호출·Disk Backup |
| **Part 5** | `L302–L399` | Auth, Markdown Formatter & 4-Scope State Recorder (`_get_cloud_platform_adc`, `_format_markdown_table`, `_record_caa_result_into_session_state`) | Keyless ADC 인증, 조회 결과 20 Row Markdown Table 변환(Token 절감), BQ CAA 실행 결과를 `temp:*`, `session`, `user:*`, `app:*` 4대 Scope에 기록 |
| **Part 6** | `L401–L523` | Core BQ CAA Stateless `:chat` + Client-Side Multi-Turn Engine (`_query_domain_caa_agent`) | `tool_context.state["domain_ca_multiturn_messages"]`에서 직전 2~3 Turn 대화를 꺼내어 GDA `:chat` (`dataAgentContext`) Streaming API를 호출하고 SQL·Row·Answer Parsing |
| **Part 7** | `L525–L709` | Session & Long-Term Memory Management Tools (`save_user_preference_and_memory`, `inspect_session_and_memory_status`) | 사용자 직무/관심부서/선호 KPI 및 핵심 Insight 저장 Tool과 4-Scope State + `search_memory()` 실시간 진단 Tool |
| **Part 8** | `L711–L805` | 3 Domain-Scoped Sub-Agent Dedicated Tools (`ask_*_caa`, `get_*_caa_info`) | 각 Sub-Agent에 1:1로 Binding되는 전용 BQ CAA 질의 Function 3종 및 Metadata 조회 Function 3종 |
| **Part 9** | `L807–L949` | Root Router Dedicated Tools & Dynamic State Prompt Template (`list_domain_caa_registry`, `run_cross_domain_caa_analysis`, `_SHARED_SESSION_MEMORY_CONTEXT`) | Architecture Registry 조회 Tool, `ThreadPoolExecutor` 기반 3-Domain 병렬 Fan-out 분석 Tool, `{state_key?}` 동적 주입 Prompt Template |
| **Part 10** | `L951–L1119` | **3 Domain Sub-Agents & Root Router Agent 정의** (`customer_marketing_subagent`, `product_profitability_subagent`, `supply_chain_logistics_subagent`, `root_agent`) | 3개 Domain 전문 `LlmAgent`와 최상위 `root_agent`(`thelook_enterprise_root_router`)의 Model, Description, Instruction, Tools, Sub-Agents, Callbacks 선언 |

---

## Part 1. Module Docstring 및 Library Import (`L1 ~ L43`)

```python
1: """Hierarchical Multi-Agent Architecture: Root Router Agent + 3 Domain-Scoped BigQuery CAA Sub-Agents
2: with Full ADK Session Object (4-Scope State + Multi-Turn History) & Memory Object (Long-Term Memory Bank).
3: 
4: Dataset: `ryan-sandbox-agent.thelook_ecommerce`
5: 
6: Architecture:
7:   [Root Agent] `thelook_enterprise_root_router` (LlmAgent)
8:     ├─ Session Management (`ctx.session` & 4 State Scopes):
9:     │    - `temp:*`   : Turn-scoped SQL, row count, and preview rows (`temp:last_caa_sql`, `temp:last_caa_rows`)
10:     │    - `session`  : Session-scoped multi-turn query history (`domain_query_history`, `domain_ca_multiturn_messages`, `session_turn_count`)
11:     │    - `user:*`   : Cross-session persistent user profile & KPI preferences (`user:profile`, `user:preferred_kpis`, `user:pinned_insights`)
12:     │    - `app:*`    : App-wide query execution counter (`app:total_caa_queries_executed`)
13:     ├─ Long-Term Memory Management (`ctx.memory_service` + Persistent JSON Backup):
14:     │    - `before_agent_callback` : `_initialize_session_and_rehydrate_memory` (initializes state & re-hydrates `MemoryService` from `.adk/long_term_memory_bank.json`)
15:     │    - `after_agent_callback`  : `_save_session_to_long_term_memory` (calls `await callback_context.add_session_to_memory()` & persists to disk)
16:     │    - Memory Tools            : `preload_memory` (`PreloadMemoryTool`), `load_memory` (`LoadMemoryTool`), `save_user_preference_and_memory`, `inspect_session_and_memory_status`
17:     │
18:     ├──> [Sub-Agent 1] `customer_marketing_subagent` (`thelook_customer_marketing_ca`)
19:     ├──> [Sub-Agent 2] `product_profitability_subagent` (`thelook_product_profitability_ca`)
20:     └──> [Sub-Agent 3] `supply_chain_logistics_subagent` (`thelook_supply_chain_ca`)
21: """
22: 
23: from __future__ import annotations
24: 
25: from concurrent.futures import ThreadPoolExecutor
26: from datetime import datetime, timezone
27: import json
28: import os
29: from pathlib import Path
30: from typing import Any
31: 
32: import google.auth
33: from google.auth.transport.requests import AuthorizedSession
34: from google.genai import types
35: 
36: from google.adk.agents import LlmAgent
37: from google.adk.agents.callback_context import CallbackContext
38: from google.adk.events import Event
39: from google.adk.tools import load_memory, preload_memory
40: from google.adk.tools.data_agent import data_agent_tool
41: from google.adk.tools.data_agent.config import DataAgentToolConfig
42: from google.adk.tools.tool_context import ToolContext
43: 
```

### Line-by-Line 상세 해설 (`L1 ~ L43`)
- **`L1–L21`**: Module 최상단 Docstring입니다.
  - `L1–L5`: `thelook_enterprise_root_router` Root Agent와 3개의 Domain-Scoped BigQuery CAA Sub-Agents로 구성된 계층형 Multi-Agent Architecture의 목적과 대상 Dataset을 명시합니다.
  - `L6–L12`: `ctx.session` 내부의 4대 State Scope(`temp:*` Turn 범위, `session` Multi-Turn 범위, `user:*` 교차 Session 사용자 영속 범위, `app:*` 전역 카운터 범위)의 설계 구조를 정의합니다.
  - `L13–L20`: `ctx.memory_service`와 Local JSON Backup(`.adk/long_term_memory_bank.json`)을 연동하는 `before_agent_callback`, `after_agent_callback`, Memory Tool(`preload_memory`, `load_memory`) 및 하위 3개 Sub-Agent 트리 구조를 문서화합니다.
- **`L23` (`from __future__ import annotations`)**: Python Type Hint(`dict[str, Any]`, `types.Content | None` 등)의 평가를 지연(Lazy Evaluation)시켜 Runtime Import 순환 참조를 방지하고 최신 Type Annotation 문법을 활성화합니다.
- **`L25` (`from concurrent.futures import ThreadPoolExecutor`)**: 복합 Domain 질문이 들어왔을 때(`run_cross_domain_caa_analysis`), 3개의 BigQuery CAA `:chat` HTTP Streaming 요청을 순차 실행(약 35~45초)하지 않고 **동시에 병렬 실행(약 12~15초)**하기 위한 표준 Thread Pool Library입니다.
- **`L26–L30` (`datetime, timezone`, `json`, `os`, `Path`, `Any`)**:
  - `L26`: Session 시작 시각 및 Query 실행 시각을 ISO-8601 UTC 문자열(`2026-10-23T02:00:00Z`)로 기록하기 위해 사용합니다.
  - `L27, L29`: `.adk/long_term_memory_bank.json` Local Memory Bank File을 읽고 쓰기 위해 사용합니다.
  - `L28`: `.env` 또는 Shell에 설정된 `GOOGLE_CLOUD_PROJECT`, `BQ_DATASET_ID` Environment Variable을 읽습니다.
- **`L32–L33` (`google.auth`, `AuthorizedSession`)**:
  - 사내 보안 정책상 `GOOGLE_API_KEY`를 사용하지 않으므로, `gcloud auth application-default login`으로 생성된 **Keyless ADC(Application Default Credentials)**를 Load하고 OAuth2 Bearer Token을 자동 갱신하며 HTTP Request를 수행하는 `AuthorizedSession`을 가져옵니다.
- **`L34` (`from google.genai import types`)**: ADK `Event` 내부의 Message 구조체인 `types.Content(role=..., parts=[types.Part.from_text(...)])`를 생성하기 위해 Google GenAI SDK의 `types` Module을 가져옵니다.
- **`L36` (`from google.adk.agents import LlmAgent`)**: Root Router Agent와 3개의 Domain Sub-Agent를 생성하는 Google ADK의 핵심 LLM 기반 Agent Class입니다.
- **`L37` (`from google.adk.agents.callback_context import CallbackContext`)**: `before_agent_callback` 및 `after_agent_callback` Function에 첫 번째 Argument로 자동 전달되는 Context Object입니다. 이를 통해 `callback_context.session`, `callback_context.state`, `callback_context.user_id`, `await callback_context.add_session_to_memory()`에 접근합니다.
- **`L38` (`from google.adk.events import Event`)**: ADK에서 사용자 질문, Model 응답, Tool 호출, Long-Term Memory 항목을 표현하는 기본 단위 Object입니다.
- **`L39` (`from google.adk.tools import load_memory, preload_memory`)**:
  - `preload_memory` (`PreloadMemoryTool`): 매 Turn LLM 추론 직전에 자동으로 `MemoryService`를 검색하여 관련 과거 대화를 `<PAST_CONVERSATIONS>` Block으로 System Prompt에 주입하는 Built-in Tool입니다.
  - `load_memory` (`LoadMemoryTool`): LLM이 판단했을 때 특정 Keyword로 과거 Session Memory를 능동적으로 조회할 수 있는 Function Tool입니다.
- **`L40–L41` (`data_agent_tool`, `DataAgentToolConfig`)**: ADK 내장 BigQuery Data Agent Utility입니다. 본 Code에서는 각 Domain CAA Agent의 Metadata(연결된 Table 목록 및 System Instruction)를 조회하는 `get_data_agent_info()` 호출에 사용합니다.
- **`L42` (`from google.adk.tools.tool_context import ToolContext`)**: Agent가 호출하는 Python Tool Function에 `tool_context: ToolContext` Parameter를 선언해 두면, ADK Runtime이 현재 실행 중인 `Session`, `State`, `search_memory()` Handle을 자동으로 주입해 줍니다.

---

## Part 2. Global 환경 설정, CAA Resource URI 및 기본 Profile 상수 (`L44 ~ L87`)

```python
44: PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
45: if PROJECT_ID in ("", "your-gcp-project-id"):
46:   PROJECT_ID = "ryan-sandbox-agent"
47: 
48: DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
49: if not DATASET_ID:
50:   DATASET_ID = "thelook_ecommerce_agent"
51: 
52: # 3 Dedicated Domain-Scoped BigQuery CAA Data Agent IDs
53: CUSTOMER_MARKETING_CA_ID = "thelook_customer_marketing_ca"
54: PRODUCT_PROFITABILITY_CA_ID = "thelook_product_profitability_ca"
55: SUPPLY_CHAIN_CA_ID = "thelook_supply_chain_ca"
56: 
57: CUSTOMER_MARKETING_CA_RESOURCE = (
58:     f"projects/{PROJECT_ID}/locations/global/dataAgents/{CUSTOMER_MARKETING_CA_ID}"
59: )
60: PRODUCT_PROFITABILITY_CA_RESOURCE = (
61:     f"projects/{PROJECT_ID}/locations/global/dataAgents/{PRODUCT_PROFITABILITY_CA_ID}"
62: )
63: SUPPLY_CHAIN_CA_RESOURCE = (
64:     f"projects/{PROJECT_ID}/locations/global/dataAgents/{SUPPLY_CHAIN_CA_ID}"
65: )
66: 
67: _TOOL_SETTINGS = DataAgentToolConfig(
68:     max_query_result_rows=30,
69:     location="global",
70: )
71: 
72: # Persistent Long-Term Memory Bank file (survives `adk web` server restarts)
73: _AGENT_DIR = Path(__file__).resolve().parent
74: _PERSISTENT_MEMORY_FILE = _AGENT_DIR / ".adk" / "long_term_memory_bank.json"
75: 
76: _DEFAULT_USER_PROFILE = {
77:     "role": "Enterprise Business Analyst",
78:     "focus_department": "All (Women / Men)",
79:     "focus_channel": "All Channels",
80: }
81: _DEFAULT_PREFERRED_KPIS = [
82:     "VIP 고객",
83:     "상품 마진율",
84:     "취소/반품 비율(환불률)",
85:     "평균 배송 소요 시간",
86: ]
87: 
```

### Line-by-Line 상세 해설 (`L44 ~ L87`)
- **`L44–L46` (`PROJECT_ID`)**: Environment Variable `GOOGLE_CLOUD_PROJECT`를 읽어 대상 GCP Project ID를 설정합니다. 만약 빈 문자열이거나 Template 초기값(`"your-gcp-project-id"`)인 경우에도 오류가 발생하지 않도록 Fallback 기본값을 지정합니다.
- **`L48–L50` (`DATASET_ID`)**: Environment Variable `BQ_DATASET_ID`를 읽어 대상 BigQuery Dataset 이름을 결정하며, 기본값은 **`thelook_ecommerce_agent`**입니다.
- **`L52–L55` (`CUSTOMER_MARKETING_CA_ID`, `PRODUCT_PROFITABILITY_CA_ID`, `SUPPLY_CHAIN_CA_ID`)**: `provision_bq_caa_demo.py`를 통해 Google Cloud GDA API에 생성된 **3개의 Domain별 BigQuery CAA Data Agent ID** 상수입니다:
  - `L53`: `thelook_customer_marketing_ca` — Domain 1 (사용자 CRM & 마케팅 Funnel)
  - `L54`: `thelook_product_profitability_ca` — Domain 2 (상품·마진·반품 수익성)
  - `L55`: `thelook_supply_chain_ca` — Domain 3 (물류센터·재고·배송 Lead Time)
- **`L57–L65` (`*_CA_RESOURCE`)**: GDA v1 API가 요구하는 전체 Resource Name 포맷(`projects/{PROJECT_ID}/locations/global/dataAgents/{AGENT_ID}`)으로 조립한 상수입니다.
- **`L67–L70` (`_TOOL_SETTINGS`)**: `DataAgentToolConfig` Object로, 최대 반환 Row 수를 `30`개로 제한하고 GDA Control Plane Location을 `"global"`로 지정합니다.
- **`L72–L74` (`_AGENT_DIR`, `_PERSISTENT_MEMORY_FILE`)**:
  - `adk web`은 기본적으로 `InMemorySessionService`와 `InMemoryMemoryService`를 사용하므로, Process를 재시작하면 RAM 상의 기억이 초기화됩니다.
  - 이를 보완하기 위해 현재 File(`agent.py`)이 위치한 Folder 하위의 `.adk/long_term_memory_bank.json` 경로를 지정하여, 모든 `user:*` Profile과 Session 분석 이력을 Local Disk에 영속 Backup합니다.
- **`L76–L86` (`_DEFAULT_USER_PROFILE`, `_DEFAULT_PREFERRED_KPIS`)**: 최초 접속한 사용자에게 부여되는 기본 `user:profile` Dictionary(`role`, `focus_department`, `focus_channel`) 및 `user:preferred_kpis` List입니다.

---

## Part 3. Local Disk Memory Bank 입출력 및 `MemoryService` 동기화 Helper (`L89 ~ L177`)

```python
89: def _utc_now_iso() -> str:
90:   return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
91: 
92: 
93: def _load_persistent_memory_store() -> dict[str, Any]:
94:   """Loads the local JSON memory bank from `.adk/long_term_memory_bank.json`."""
95:   if not _PERSISTENT_MEMORY_FILE.exists():
96:     return {"user_profiles": {}, "sessions": {}, "explicit_memories": []}
97:   try:
98:     return json.loads(_PERSISTENT_MEMORY_FILE.read_text(encoding="utf-8"))
99:   except Exception:
100:     return {"user_profiles": {}, "sessions": {}, "explicit_memories": []}
101: 
102: 
103: def _save_persistent_memory_store(store: dict[str, Any]) -> None:
104:   """Persists the local JSON memory bank to `.adk/long_term_memory_bank.json`."""
105:   try:
106:     _PERSISTENT_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
107:     _PERSISTENT_MEMORY_FILE.write_text(
108:         json.dumps(store, ensure_ascii=False, indent=2),
109:         encoding="utf-8",
110:     )
111:   except Exception:
112:     pass
113: 
114: 
115: async def _sync_store_into_adk_memory_service(
116:     inv_ctx: Any,
117:     app_name: str,
118:     user_id: str,
119:     store: dict[str, Any],
120: ) -> None:
121:   """Synchronizes persisted session history and explicit insights into ADK `MemoryService`."""
122:   if inv_ctx is None or getattr(inv_ctx, "memory_service", None) is None:
123:     return
124: 
125:   rehydrated_events: list[Event] = []
126:   for sess_data in store.get("sessions", {}).values():
127:     for q_item in sess_data.get("domain_query_history", []):
128:       summary_txt = (
129:           f"[과거 도메인 분석 이력] 도메인={q_item.get('domain')} | 질문={q_item.get('query')} | "
130:           f"SQL={q_item.get('generated_sql')} | 요약={q_item.get('answer_preview')}"
131:       )
132:       rehydrated_events.append(
133:           Event(
134:               author=q_item.get("caa_agent_id", "domain_caa_subagent"),
135:               content=types.Content(
136:                   role="model",
137:                   parts=[types.Part.from_text(text=summary_txt)],
138:               ),
139:           )
140:       )
141:     for ev_item in sess_data.get("events", []):
142:       text = ev_item.get("text", "").strip()
143:       if text:
144:         rehydrated_events.append(
145:             Event(
146:                 author=ev_item.get("author", "thelook_enterprise_root_router"),
147:                 content=types.Content(
148:                     role=ev_item.get("role", "model"),
149:                     parts=[types.Part.from_text(text=text)],
150:                 ),
151:             )
152:         )
153: 
154:   for mem_item in store.get("explicit_memories", []):
155:     text = mem_item.get("text", "").strip()
156:     if text:
157:       rehydrated_events.append(
158:           Event(
159:               author="long_term_memory_bank",
160:               content=types.Content(
161:                   role="model",
162:                   parts=[types.Part.from_text(text=f"[장기 기억 인사이트] {text}")],
163:               ),
164:           )
165:       )
166: 
167:   if rehydrated_events:
168:     try:
169:       await inv_ctx.memory_service.add_events_to_memory(
170:           app_name=app_name,
171:           user_id=user_id,
172:           events=rehydrated_events,
173:           session_id="persisted_long_term_memory",
174:       )
175:     except Exception:
176:       pass
177: 
```

### Line-by-Line 상세 해설 (`L89 ~ L177`)
- **`L89–L90` (`_utc_now_iso`)**: 현재 UTC 시각을 `"YYYY-MM-DDTHH:MM:SSZ"` 포맷 문자열로 반환하는 Utility Function입니다.
- **`L93–L100` (`_load_persistent_memory_store`)**:
  - `L95–L96`: `.adk/long_term_memory_bank.json` File이 아직 없으면 빈 기본 Schema(`{"user_profiles": {}, "sessions": {}, "explicit_memories": []}`)를 반환합니다.
  - `L97–L100`: File이 존재하면 UTF-8로 읽어 JSON Parsing을 수행하며, 예외 발생 시에도 안전하게 기본 Schema를 반환합니다.
- **`L103–L112` (`_save_persistent_memory_store`)**:
  - `L106`: 상위 Folder(`.adk/`)가 없으면 `mkdir(parents=True, exist_ok=True)`로 자동 생성합니다.
  - `L107–L110`: 한글이 유니코드 이스케이프(`\uXXXX`)로 깨지지 않도록 `ensure_ascii=False, indent=2` 옵션으로 JSON File을 저장합니다.
- **`L115–L176` (`_sync_store_into_adk_memory_service`)**:
  - Local JSON File(`store`)에 저장된 과거 기록들을 ADK Runtime의 `inv_ctx.memory_service` (`InMemoryMemoryService` 또는 `VertexAiMemoryBankService`) 안으로 재주입(Re-hydration)하는 비동기 Function입니다.
  - `L122–L123`: `inv_ctx`나 `memory_service`가 Binding되지 않은 환경에서는 안전하게 조기 종료(`return`)합니다.
  - `L125–L140`: 과거 모든 Session에서 실행된 `domain_query_history` 항목(Domain, 질문, 생성된 SQL, 답변 요약)을 순회하며 ADK 표준 `Event(author=..., content=types.Content(...))` Object로 변환해 `rehydrated_events` List에 추가합니다.
  - `L141–L152`: 과거 Session의 일반 대화 Event(`events`) Text도 `Event` Object로 복원하여 추가합니다.
  - `L154–L165`: 사용자가 `save_user_preference_and_memory` Tool을 통해 명시적으로 저장을 요청한 비즈니스 Insight(`explicit_memories`)를 `author="long_term_memory_bank"`인 `Event` Object로 변환합니다.
  - `L167–L176`: 복원된 `rehydrated_events`가 존재하면 `await inv_ctx.memory_service.add_events_to_memory(...)`를 호출하여 ADK `MemoryService` Index에 등록합니다. 덕분에 `adk web` Server를 재시작해도 `preload_memory`와 `load_memory`가 과거 기억을 즉시 검색할 수 있습니다.

---

## Part 4. ADK Lifecycle Callbacks — Session 초기화 및 Long-Term Memory 저장 (`L179 ~ L300`)

```python
179: # ==============================================================================
180: # ADK Lifecycle Callbacks: Session State Init + Long-Term Memory Sync
181: # ==============================================================================
182: async def _initialize_session_and_rehydrate_memory(
183:     callback_context: CallbackContext,
184: ) -> None:
185:   """`before_agent_callback`: Initializes 4-Scope Session State and re-hydrates `MemoryService`."""
186:   state = callback_context.state
187:   session = callback_context.session
188:   user_id = callback_context.user_id or "default_user"
189:   app_name = session.app_name or "bq_caa_3domain_multi_agent"
190: 
191:   store = _load_persistent_memory_store()
192:   persisted_user = store.get("user_profiles", {}).get(user_id, {})
193: 
194:   is_new_session = "session_started_at" not in state
195: 
196:   # 1. Session-Scoped State (persists across turns within the current session)
197:   if is_new_session:
198:     state["session_started_at"] = _utc_now_iso()
199:     state["session_turn_count"] = 0
200:     state["active_domain"] = "Root Router"
201:     state["domain_query_history"] = []
202:     state["domain_ca_multiturn_messages"] = {}
203: 
204:   # 2. User-Scoped State (`user:*` persists across different sessions for the same user)
205:   if is_new_session or "user:profile" not in state:
206:     state["user:profile"] = persisted_user.get(
207:         "profile", dict(_DEFAULT_USER_PROFILE)
208:     )
209:   if is_new_session or "user:preferred_kpis" not in state:
210:     state["user:preferred_kpis"] = persisted_user.get(
211:         "preferred_kpis", list(_DEFAULT_PREFERRED_KPIS)
212:     )
213:   if is_new_session or "user:pinned_insights" not in state:
214:     state["user:pinned_insights"] = persisted_user.get("pinned_insights", [])
215: 
216:   # 3. App-Scoped State (`app:*` shared across all users/sessions)
217:   if is_new_session or "app:total_caa_queries_executed" not in state:
218:     state["app:total_caa_queries_executed"] = store.get(
219:         "total_caa_queries_executed", 0
220:     )
221: 
222:   # 4. Sync persisted memories into ADK `MemoryService` (`InMemoryMemoryService`)
223:   inv_ctx = callback_context._invocation_context  # pylint: disable=protected-access
224:   await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)
225: 
226: 
227: async def _save_session_to_long_term_memory(
228:     callback_context: CallbackContext,
229: ) -> types.Content | None:
230:   """`after_agent_callback`: Indexes `ctx.session` into ADK `MemoryService` and persists to disk."""
231:   session = callback_context.session
232:   state = callback_context.state
233:   user_id = callback_context.user_id or "default_user"
234:   app_name = session.app_name or "bq_caa_3domain_multi_agent"
235: 
236:   # 1. Native ADK Memory Object indexing (`await callback_context.add_session_to_memory()`)
237:   try:
238:     await callback_context.add_session_to_memory()
239:   except Exception:
240:     pass
241: 
242:   # 2. Merge & persist session events and `user:*` / `app:*` state to `.adk/long_term_memory_bank.json`
243:   store = _load_persistent_memory_store()
244:   existing_user = store.get("user_profiles", {}).get(user_id, {})
245: 
246:   cur_profile = state.get("user:profile")
247:   if cur_profile and cur_profile != _DEFAULT_USER_PROFILE:
248:     merged_profile = cur_profile
249:   else:
250:     merged_profile = existing_user.get("profile") or cur_profile or dict(_DEFAULT_USER_PROFILE)
251: 
252:   cur_kpis = state.get("user:preferred_kpis")
253:   if cur_kpis and cur_kpis != _DEFAULT_PREFERRED_KPIS:
254:     merged_kpis = cur_kpis
255:   else:
256:     merged_kpis = existing_user.get("preferred_kpis") or cur_kpis or list(_DEFAULT_PREFERRED_KPIS)
257: 
258:   cur_pinned = state.get("user:pinned_insights") or existing_user.get("pinned_insights", [])
259: 
260:   store.setdefault("user_profiles", {})[user_id] = {
261:       "profile": merged_profile,
262:       "preferred_kpis": merged_kpis,
263:       "pinned_insights": cur_pinned,
264:       "updated_at": _utc_now_iso(),
265:   }
266:   store["total_caa_queries_executed"] = max(
267:       int(store.get("total_caa_queries_executed", 0)),
268:       int(state.get("app:total_caa_queries_executed", 0)),
269:   )
270: 
271:   serialized_events: list[dict[str, str]] = []
272:   for ev in session.events[-30:]:
273:     if not ev.content or not ev.content.parts:
274:       continue
275:     texts = [p.text for p in ev.content.parts if getattr(p, "text", None)]
276:     joined = "\n".join(texts).strip()
277:     if joined:
278:       serialized_events.append({
279:           "author": ev.author or "agent",
280:           "role": ev.content.role or "model",
281:           "text": joined[:2000],
282:       })
283: 
284:   existing_sess = store.get("sessions", {}).get(session.id, {})
285:   cur_history = state.get("domain_query_history") or existing_sess.get("domain_query_history", [])
286: 
287:   store.setdefault("sessions", {})[session.id] = {
288:       "session_id": session.id,
289:       "user_id": user_id,
290:       "updated_at": _utc_now_iso(),
291:       "active_domain": state.get("active_domain") or existing_sess.get("active_domain", "Root Router"),
292:       "domain_query_history": cur_history[-15:],
293:       "events": serialized_events or existing_sess.get("events", []),
294:   }
295:   _save_persistent_memory_store(store)
296: 
297:   inv_ctx = callback_context._invocation_context  # pylint: disable=protected-access
298:   await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)
299:   return None
300: 
```

### Line-by-Line 상세 해설 (`L179 ~ L300`)
- **`L182–L194` (`_initialize_session_and_rehydrate_memory` — `before_agent_callback`)**:
  - `L186–L189`: 매 Turn Agent가 실행되기 직전에 호출되며, `callback_context`로부터 현재 `state` Proxy Object, `session` Object, `user_id`, `app_name`을 추출합니다.
  - `L191–L194`: Disk에서 영속 저장소(`store`)를 읽고, `"session_started_at"` Key의 존재 여부로 현재 Session이 방금 생성된 새 Session(`+ New Session`)인지 판별합니다 (`is_new_session`).
- **`L196–L202` (Scope 2 — Session-Scoped State 초기화)**:
  - 새 Session일 때만 초기화되는 Key들입니다 (`session_started_at`, `session_turn_count = 0`, `active_domain = "Root Router"`, `domain_query_history = []`, `domain_ca_multiturn_messages = {}`).
  - 동일 Session의 Turn 2, Turn 3에서는 `is_new_session`이 `False`이므로 이전 Turn에서 누적된 List/Dictionary가 그대로 보존됩니다.
- **`L204–L214` (Scope 3 — User-Scoped State `user:*` 초기화 및 교차 Session 복원)**:
  - 사용자가 `+ New Session`을 눌러 새 Session을 열더라도, 이전 Session에서 저장해 둔 `persisted_user`의 `profile`(직책, 관심 부서, 관심 채널), `preferred_kpis`, `pinned_insights`를 `state["user:profile"]`, `state["user:preferred_kpis"]`, `state["user:pinned_insights"]`에 자동으로 복원합니다.
- **`L216–L220` (Scope 4 — App-Scoped State `app:*` 복원)**:
  - Application 전체 누적 BigQuery CAA Query 실행 횟수(`app:total_caa_queries_executed`)를 복원합니다.
- **`L222–L224`**: `_sync_store_into_adk_memory_service`를 호출해 LLM 추론이 시작되기 전에 `MemoryService`를 최신 상태로 동기화합니다.
- **`L227–L300` (`_save_session_to_long_term_memory` — `after_agent_callback`)**:
  - `L237–L240` (`await callback_context.add_session_to_memory()`): 매 Turn 응답 완료 직후 ADK 표준 API를 호출하여 현재 `callback_context.session` Object를 `MemoryService`에 즉시 Indexing합니다.
  - `L243–L269`: 현재 `state`의 `user:profile`, `user:preferred_kpis`, `user:pinned_insights`, `app:total_caa_queries_executed`를 기존 Disk 저장소 값과 안전하게 Merge합니다. 만약 새 Session에서 아직 Profile을 수정하지 않아 기본값(`_DEFAULT_USER_PROFILE`) 상태라면, 기존에 저장된 사용자 Profile(`existing_user.get("profile")`)이 덮어써지지 않도록 보호합니다 (`L247–L250`).
  - `L271–L282`: 현재 `session.events` 중 최근 30개 Event의 Text(`parts`)를 추출하여 각 2,000자 이내로 직렬화(`serialized_events`)합니다.
  - `L284–L295`: `store["sessions"][session.id]`에 현재 Session의 Metadata, `domain_query_history`(최근 15건), `events`를 기록하고 `_save_persistent_memory_store(store)`로 Disk에 영구 저장합니다.
  - `L299` (`return None`): ADK `after_agent_callback` 규약상 `None`을 반환하면 Agent가 생성한 원래 응답을 변경 없이 그대로 사용자에게 전달합니다.

---

## Part 5. Keyless ADC 인증, Markdown Table 변환 및 4-Scope State 기록 (`L302 ~ L399`)

```python
302: # ==============================================================================
303: # BigQuery CAA Helper with Session Multi-Turn History & State Recording
304: # ==============================================================================
305: def _get_cloud_platform_adc():
306:   """Loads Keyless ADC with `cloud-platform` scope and quota project `ryan-sandbox-agent`."""
307:   creds, _ = google.auth.default(
308:       scopes=["https://www.googleapis.com/auth/cloud-platform"]
309:   )
310:   if hasattr(creds, "with_quota_project"):
311:     creds = creds.with_quota_project(PROJECT_ID)
312:   return creds
313: 
314: 
315: def _format_markdown_table(rows: list[dict[str, Any]], max_rows: int = 20) -> str:
316:   """Converts BigQuery result rows into a compact Markdown table (Token Diet)."""
317:   if not rows:
318:     return ""
319:   headers = list(rows[0].keys())
320:   header_line = "| " + " | ".join(headers) + " |"
321:   sep_line = "| " + " | ".join("---" for _ in headers) + " |"
322:   body_lines = [
323:       "| " + " | ".join(str(r.get(h, "")) for h in headers) + " |"
324:       for r in rows[:max_rows]
325:   ]
326:   footer = (
327:       f"\n*(Showing top {max_rows} of {len(rows)} rows)*"
328:       if len(rows) > max_rows
329:       else f"\n*(Total {len(rows)} rows)*"
330:   )
331:   return "\n".join([header_line, sep_line, *body_lines]) + footer
332: 
333: 
334: def _record_caa_result_into_session_state(
335:     state: Any,
336:     agent_id: str,
337:     domain_label: str,
338:     data_agent_name: str,
339:     query: str,
340:     generated_sql: str,
341:     rows: list[dict[str, Any]],
342:     ca_final_answer: str,
343:     session_id: str = "active_session",
344:     user_id: str = "default_user",
345: ) -> None:
346:   """Updates all 4 ADK Session State scopes (`temp:`, `session`, `user:`, `app:`) and disk store."""
347:   # 1. `temp:*` (Turn / Invocation Scope)
348:   state["temp:last_caa_domain"] = domain_label
349:   state["temp:last_caa_agent"] = data_agent_name
350:   state["temp:last_caa_sql"] = generated_sql
351:   state["temp:last_caa_row_count"] = len(rows)
352:   state["temp:last_caa_rows"] = rows[:20]
353: 
354:   # 2. Session Scope (Multi-Turn History within current session)
355:   turn_num = int(state.get("session_turn_count", 0)) + 1
356:   state["session_turn_count"] = turn_num
357:   state["active_domain"] = domain_label
358: 
359:   history_entry = {
360:       "turn": turn_num,
361:       "timestamp": _utc_now_iso(),
362:       "domain": domain_label,
363:       "caa_agent_id": agent_id,
364:       "query": query,
365:       "generated_sql": generated_sql,
366:       "row_count": len(rows),
367:       "answer_preview": ca_final_answer[:300],
368:   }
369:   history = list(state.get("domain_query_history", []))
370:   history.append(history_entry)
371:   state["domain_query_history"] = history[-20:]
372: 
373:   # Store multi-turn messages per domain CAA agent for context chaining
374:   multiturn_map = dict(state.get("domain_ca_multiturn_messages", {}))
375:   agent_msgs = list(multiturn_map.get(agent_id, []))
376:   agent_msgs.append({"userMessage": {"text": query}})
377:   sys_summary = ca_final_answer or f"Executed SQL:\n{generated_sql}"
378:   agent_msgs.append({"systemMessage": {"text": {"parts": [sys_summary[:1000]]}}})
379:   multiturn_map[agent_id] = agent_msgs[-6:]  # Keep last 3 turns (6 messages)
380:   state["domain_ca_multiturn_messages"] = multiturn_map
381: 
382:   # 3. App Scope (`app:*`)
383:   store = _load_persistent_memory_store()
384:   new_total = max(
385:       int(store.get("total_caa_queries_executed", 0)),
386:       int(state.get("app:total_caa_queries_executed", 0)),
387:   ) + 1
388:   state["app:total_caa_queries_executed"] = new_total
389:   store["total_caa_queries_executed"] = new_total
390: 
391:   sess_entry = store.setdefault("sessions", {}).setdefault(
392:       session_id,
393:       {"session_id": session_id, "user_id": user_id, "domain_query_history": [], "events": []},
394:   )
395:   sess_entry["updated_at"] = _utc_now_iso()
396:   sess_entry["active_domain"] = domain_label
397:   sess_entry["domain_query_history"] = state["domain_query_history"][-15:]
398:   _save_persistent_memory_store(store)
399: 
```

### Line-by-Line 상세 해설 (`L302 ~ L399`)
- **`L305–L312` (`_get_cloud_platform_adc`)**:
  - `L307–L309`: `google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])`로 Local ADC 자격증명을 Load합니다.
  - `L310–L311` (`creds.with_quota_project(PROJECT_ID)`): 기업 환경에서 흔히 발생하는 `HTTP 403 PERMISSION_DENIED: Consumer project not set` 오류를 방지하기 위해, HTTP Header(`x-goog-user-project`)에 대상 `PROJECT_ID`를 강제로 Binding합니다.
- **`L315–L331` (`_format_markdown_table`)**:
  - BigQuery CAA가 반환한 JSON Row List(`rows`)를 깔끔한 Markdown Table로 변환하되, **최대 `max_rows=20` 행까지만 잘라서(Truncation)** 반환합니다.
  - **설계 이유 (Token Diet)**: 수백~수천 Row의 Raw JSON을 LLM Context에 그대로 반환하면 단일 Turn에 수만 Token이 소모됩니다. 상위 20 Row만 Markdown Table로 변환하면 가독성과 Token 비용 절감을 동시에 확보할 수 있습니다.
- **`L334–L398` (`_record_caa_result_into_session_state`)**:
  - **`L348–L352` (Scope 1 — `temp:*` Turn 임시 State 기록)**:
    - `temp:` 접두사가 붙은 State Key는 ADK가 **현재 Turn(Invocation) 동안만 유지하고 Turn 종료 시 자동 소멸**시킵니다. 방금 실행된 `generated_sql`과 상위 20개 Data Row(`rows[:20]`)를 기록합니다.
  - **`L355–L371` (Scope 2 — Session 누적 이력 `domain_query_history` 기록)**:
    - `session_turn_count`를 1 증가시키고, 현재 Turn에서 실행된 Domain, CAA Agent ID, 질문, 생성된 SQL, 반환 Row 수, 답변 요약(300자)을 `state["domain_query_history"]`에 누적(최대 20건 유지)합니다.
    - 이 값은 System Prompt의 `{domain_query_history?}` Placeholder를 통해 Root 및 Sub-Agent에게 매 Turn 주입되므로, 사용자가 Domain을 넘나들며 후속 질문을 해도 이전 Context를 정확히 참조합니다.
  - **`L374–L380` (Domain별 Multi-Turn Message Sliding Window 관리)**:
    - 각 BQ CAA Agent ID(`agent_id`)를 Key로 하는 List에 `{"userMessage": {"text": query}}`와 `{"systemMessage": {"text": {"parts": [sys_summary[:1000]]}}}` 쌍을 추가합니다.
    - **`L379` (`agent_msgs[-6:]`)**: 최근 3 Turn(질문+응답 6개 Message)만 Sliding Window로 유지하여, 후속 질문 시 Multi-Turn Context는 이어가면서 GDA `:chat` API의 Input Token이 무한정 증가하는 것을 차단합니다.
  - **`L383–L398` (Scope 4 — `app:*` 전역 카운터 증가 및 즉시 Disk Backup)**:
    - `state["app:total_caa_queries_executed"]`를 `+1` 증가시키고 `.adk/long_term_memory_bank.json`에 즉시 반영합니다.

---

## Part 6. BigQuery CAA `:chat` Streaming 호출 및 Client-Side Multi-Turn Engine (`L401 ~ L523`)

```python
401: def _query_domain_caa_agent(
402:     agent_id: str,
403:     domain_label: str,
404:     query: str,
405:     tool_context: ToolContext | None = None,
406: ) -> dict[str, Any]:
407:   """Calls a specific domain-scoped BigQuery CAA Data Agent directly via `:chat` with Multi-Turn Session History."""
408:   data_agent_name = f"projects/{PROJECT_ID}/locations/global/dataAgents/{agent_id}"
409:   session = AuthorizedSession(_get_cloud_platform_adc())
410:   url = f"https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/global:chat"
411: 
412:   # Chain previous domain conversation turns from `tool_context.state` if available
413:   messages: list[dict[str, Any]] = []
414:   if tool_context is not None:
415:     multiturn_map = tool_context.state.get("domain_ca_multiturn_messages", {})
416:     if isinstance(multiturn_map, dict) and agent_id in multiturn_map:
417:       messages.extend(multiturn_map[agent_id][-4:])
418:   messages.append({"userMessage": {"text": query}})
419: 
420:   payload = {
421:       "messages": messages,
422:       "dataAgentContext": {"dataAgent": data_agent_name},
423:       "clientIdEnum": "GOOGLE_ADK",
424:   }
425:   headers = {
426:       "Content-Type": "application/json",
427:       "X-Goog-API-Client": "GOOGLE_ADK",
428:   }
429: 
430:   chunks: list[dict[str, Any]] = []
431:   accumulator = ""
432:   try:
433:     with session.post(url, json=payload, headers=headers, stream=True, timeout=120) as resp:
434:       if not resp.ok:
435:         return {
436:             "status": "ERROR",
437:             "domain": domain_label,
438:             "data_agent": data_agent_name,
439:             "error_details": f"HTTP {resp.status_code}: {resp.text}",
440:         }
441:       for line in resp.iter_lines():
442:         if not line:
443:           continue
444:         decoded = line.decode("utf-8")
445:         if decoded == "[{":
446:           accumulator = "{"
447:         elif decoded == "}]":
448:           accumulator += "}"
449:         elif decoded == ",":
450:           continue
451:         else:
452:           accumulator += decoded
453:         try:
454:           parsed = json.loads(accumulator)
455:           accumulator = ""
456:           if isinstance(parsed, dict):
457:             chunks.append(parsed)
458:         except ValueError:
459:           continue
460:   except Exception as exc:
461:     return {
462:         "status": "ERROR",
463:         "domain": domain_label,
464:         "data_agent": data_agent_name,
465:         "error_details": str(exc),
466:     }
467: 
468:   thoughts: list[str] = []
469:   final_texts: list[str] = []
470:   generated_sql = ""
471:   rows: list[dict[str, Any]] = []
472: 
473:   for item in chunks:
474:     sm = item.get("systemMessage", {})
475:     if not isinstance(sm, dict):
476:       continue
477:     if "text" in sm and isinstance(sm["text"], dict):
478:       parts = sm["text"].get("parts", [])
479:       text_type = sm["text"].get("textType", "")
480:       joined = "".join(str(p) for p in parts).strip()
481:       if joined:
482:         if text_type == "THOUGHT":
483:           thoughts.append(joined)
484:         else:
485:           final_texts.append(joined)
486:     if "data" in sm and isinstance(sm["data"], dict):
487:       data_obj = sm["data"]
488:       if data_obj.get("generatedSql"):
489:         generated_sql = data_obj["generatedSql"].strip()
490:       res_obj = data_obj.get("result")
491:       if isinstance(res_obj, dict) and isinstance(res_obj.get("data"), list):
492:         rows = res_obj["data"]
493: 
494:   markdown_table = _format_markdown_table(rows, max_rows=20)
495:   ca_final_answer = "\n\n".join(final_texts).strip()
496: 
497:   if tool_context is not None:
498:     _record_caa_result_into_session_state(
499:         state=tool_context.state,
500:         agent_id=agent_id,
501:         domain_label=domain_label,
502:         data_agent_name=data_agent_name,
503:         query=query,
504:         generated_sql=generated_sql,
505:         rows=rows,
506:         ca_final_answer=ca_final_answer,
507:         session_id=tool_context.session.id,
508:         user_id=tool_context.user_id or "default_user",
509:     )
510: 
511:   return {
512:       "status": "SUCCESS",
513:       "domain": domain_label,
514:       "data_agent": data_agent_name,
515:       "query": query,
516:       "multiturn_context_messages_sent": len(messages),
517:       "generated_sql": generated_sql,
518:       "row_count": len(rows),
519:       "markdown_table": markdown_table,
520:       "ca_final_answer": ca_final_answer,
521:       "thought_summary": thoughts[-1] if thoughts else "",
522:   }
523: 
```

### Line-by-Line 상세 해설 (`L401 ~ L523`)
- **`L408–L410`**: 호출할 대상 Domain CAA의 Resource Name과 GDA `:chat` Endpoint URL(`https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/global:chat`)을 준비합니다.
- **`L413–L418` (Client-Side Multi-Turn Chaining)**:
  - `tool_context.state["domain_ca_multiturn_messages"][agent_id]`에서 해당 Domain CAA와 주고받았던 직전 2 Turn(`[-4:]`, 질문 2개 + 응답 2개)을 꺼내어 `messages` 배열 앞부분에 넣고, 마지막에 현재 질문(`{"userMessage": {"text": query}}`)을 추가합니다.
- **`L420–L428` (Stateless `dataAgentContext` + Multi-Turn `messages` Payload)**:
  - `"dataAgentContext": {"dataAgent": data_agent_name}`을 사용하여 GDA Server 측에는 별도의 Stateful Conversation Lock을 만들지 않으면서, Client-Side(`Session.state`)에서 관리하는 `messages` 배열로 Multi-Turn Context를 전달합니다.
- **`L430–L466` (Streaming JSON Array Parser)**:
  - GDA `:chat` Endpoint는 `[{...}, {...}, ...]` 형태의 Multi-Line JSON Array Stream을 반환합니다.
  - `resp.iter_lines()`로 한 줄씩 읽으면서 시작 브래킷(`"[{` -> `"{"`), 종료 브래킷(`"}]" ` -> `"}"`), 구분 쉼표(`","`)를 처리해 개별 JSON Object(`parsed`)가 완성될 때마다 `chunks` List에 담습니다.
- **`L468–L495` (`systemMessage` 추출)**:
  - 각 Chunk의 `systemMessage` 안에서:
    1. `L477–L485` (`sm["text"]`): `textType == "THOUGHT"`이면 내부 추론 과정(`thoughts`)에 담고, `"FINAL_RESPONSE"`이면 최종 자연어 해설(`final_texts`)에 담습니다.
    2. `L488–L489` (`sm["data"]["generatedSql"]`): BigQuery CAA가 생성한 최종 SQL Query를 `generated_sql`에 저장합니다.
    3. `L490–L492` (`sm["data"]["result"]["data"]`): BigQuery 실행 결과 Row List를 `rows`에 저장합니다.
    4. `L494`: `_format_markdown_table(rows, max_rows=20)`으로 상위 20 Row를 Markdown Table로 변환합니다.
- **`L497–L509`**: `tool_context`가 존재하면 `_record_caa_result_into_session_state(...)`를 호출해 4-Scope `Session.state`를 즉시 갱신합니다.
- **`L511–L522`**: Sub-Agent LLM이 최종 답변을 구성하는 데 필요한 핵심 Field(`generated_sql`, `row_count`, `markdown_table`, `ca_final_answer`, `multiturn_context_messages_sent`, `thought_summary`)를 Dictionary로 반환합니다.

---

## Part 7. Session 및 Long-Term Memory 제어용 Tool Functions (`L525 ~ L709`)

```python
525: # ==============================================================================
526: # Session & Long-Term Memory Management Tools (Exposed to Root & Sub-Agents)
527: # ==============================================================================
528: async def save_user_preference_and_memory(
529:     role: str = "",
530:     focus_department: str = "",
531:     focus_channel: str = "",
532:     preferred_kpis_csv: str = "",
533:     key_insight_to_remember: str = "",
534:     tool_context: ToolContext | None = None,
535: ) -> dict[str, Any]:
536:   """Saves user analysis preferences (`user:*` state) and explicit long-term business insights (`MemoryService`).
537: 
538:   Call this tool when the user states their role, preferred department/channel/KPIs, or asks to
539:   remember a specific analytical finding across future sessions.
540: 
541:   Args:
542:       role: User's job title or role (e.g., 'MD 본부장', '마케팅 팀장', 'SCM 총괄').
543:       focus_department: Preferred department filter (e.g., 'Women', 'Men').
544:       focus_channel: Preferred marketing channel filter (e.g., 'Search', 'Email').
545:       preferred_kpis_csv: Comma-separated KPIs of interest (e.g., 'VIP 고객, 상품 마진율, 환불률').
546:       key_insight_to_remember: Important analytical finding or business rule to remember across sessions.
547:   """
548:   if tool_context is None:
549:     return {"status": "ERROR", "message": "ToolContext is required."}
550: 
551:   state = tool_context.state
552:   user_id = tool_context.user_id or "default_user"
553:   app_name = tool_context.session.app_name or "bq_caa_3domain_multi_agent"
554: 
555:   store = _load_persistent_memory_store()
556:   existing_user = store.get("user_profiles", {}).get(user_id, {})
557: 
558:   profile = dict(
559:       state.get("user:profile")
560:       or existing_user.get("profile")
561:       or _DEFAULT_USER_PROFILE
562:   )
563:   if role.strip():
564:     profile["role"] = role.strip()
565:   if focus_department.strip():
566:     profile["focus_department"] = focus_department.strip()
567:   if focus_channel.strip():
568:     profile["focus_channel"] = focus_channel.strip()
569:   state["user:profile"] = profile
570: 
571:   if preferred_kpis_csv.strip():
572:     kpis = [k.strip() for k in preferred_kpis_csv.split(",") if k.strip()]
573:     if kpis:
574:       state["user:preferred_kpis"] = kpis
575: 
576:   pinned = list(
577:       state.get("user:pinned_insights")
578:       or existing_user.get("pinned_insights", [])
579:   )
580:   memory_summary_parts = [
581:       f"[사용자 프로필/선호 설정] 역할={profile.get('role')}, 관심부서={profile.get('focus_department')}, "
582:       f"관심채널={profile.get('focus_channel')}, 핵심KPI={state.get('user:preferred_kpis')}"
583:   ]
584: 
585:   if key_insight_to_remember.strip():
586:     entry = {
587:         "timestamp": _utc_now_iso(),
588:         "insight": key_insight_to_remember.strip(),
589:     }
590:     pinned.append(entry)
591:     state["user:pinned_insights"] = pinned[-20:]
592:     memory_summary_parts.append(f"[핵심 분석 인사이트 기억] {key_insight_to_remember.strip()}")
593: 
594:   memory_text = " | ".join(memory_summary_parts)
595: 
596:   # Persist to local JSON store and index into ADK MemoryService immediately
597:   store.setdefault("user_profiles", {})[user_id] = {
598:       "profile": state["user:profile"],
599:       "preferred_kpis": state.get("user:preferred_kpis", []),
600:       "pinned_insights": state.get("user:pinned_insights", []),
601:       "updated_at": _utc_now_iso(),
602:   }
603:   store.setdefault("explicit_memories", []).append({
604:       "timestamp": _utc_now_iso(),
605:       "user_id": user_id,
606:       "text": memory_text,
607:   })
608:   _save_persistent_memory_store(store)
609: 
610:   inv_ctx = tool_context._invocation_context  # pylint: disable=protected-access
611:   await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)
612: 
613:   return {
614:       "status": "SUCCESS",
615:       "updated_user_profile": state["user:profile"],
616:       "updated_preferred_kpis": state.get("user:preferred_kpis", []),
617:       "pinned_insights_count": len(state.get("user:pinned_insights", [])),
618:       "indexed_to_memory_service": memory_text,
619:   }
620: 
621: 
622: async def inspect_session_and_memory_status(
623:     memory_search_query: str = "VIP 마진율 환불률 물류 배송",
624:     tool_context: ToolContext | None = None,
625: ) -> dict[str, Any]:
626:   """Inspects the current ADK `Session` object (4-Scope State & Events) and `Memory` object (`search_memory`).
627: 
628:   Call this tool when the user asks to verify or inspect Session State (`temp:`, `session`, `user:`, `app:`)
629:   or Long-Term Memory (`MemoryService` / past sessions).
630: 
631:   Args:
632:       memory_search_query: Keyword query to test retrieving past memories from ADK `MemoryService`.
633:   """
634:   if tool_context is None:
635:     return {"status": "ERROR", "message": "ToolContext is required."}
636: 
637:   session = tool_context.session
638:   state = tool_context.state
639:   user_id = tool_context.user_id or "default_user"
640:   app_name = session.app_name or "bq_caa_3domain_multi_agent"
641: 
642:   store = _load_persistent_memory_store()
643:   inv_ctx = tool_context._invocation_context  # pylint: disable=protected-access
644:   await _sync_store_into_adk_memory_service(inv_ctx, app_name, user_id, store)
645: 
646:   # Search ADK MemoryService
647:   matched_memories: list[dict[str, str]] = []
648:   try:
649:     mem_resp = await tool_context.search_memory(memory_search_query)
650:     for m in mem_resp.memories[:10]:
651:       parts_text = " ".join(
652:           p.text for p in (m.content.parts if m.content and m.content.parts else []) if getattr(p, "text", None)
653:       )
654:       matched_memories.append({
655:           "author": m.author or "agent",
656:           "timestamp": m.timestamp or "",
657:           "text_preview": parts_text[:300],
658:       })
659:   except Exception as exc:
660:     matched_memories.append({"error": str(exc)})
661: 
662:   return {
663:       "status": "SUCCESS",
664:       "session_object": {
665:           "session_id": session.id,
666:           "app_name": session.app_name,
667:           "user_id": session.user_id,
668:           "total_events_in_current_session": len(session.events),
669:           "session_started_at": state.get("session_started_at"),
670:           "session_turn_count": state.get("session_turn_count", 0),
671:           "active_domain": state.get("active_domain", "Root Router"),
672:       },
673:       "state_scopes": {
674:           "1_temp_scope (current turn only)": {
675:               "temp:last_caa_domain": state.get("temp:last_caa_domain"),
676:               "temp:last_caa_agent": state.get("temp:last_caa_agent"),
677:               "temp:last_caa_row_count": state.get("temp:last_caa_row_count"),
678:               "temp:last_caa_sql_present": bool(state.get("temp:last_caa_sql")),
679:           },
680:           "2_session_scope (multi-turn within session)": {
681:               "domain_query_history_count": len(state.get("domain_query_history", [])),
682:               "domain_query_history": state.get("domain_query_history", [])[-5:],
683:               "tracked_multiturn_caa_agents": list(
684:                   state.get("domain_ca_multiturn_messages", {}).keys()
685:               ),
686:           },
687:           "3_user_scope (persists across all sessions for user)": {
688:               "user:profile": state.get("user:profile"),
689:               "user:preferred_kpis": state.get("user:preferred_kpis"),
690:               "user:pinned_insights": state.get("user:pinned_insights"),
691:           },
692:           "4_app_scope (global across app)": {
693:               "app:total_caa_queries_executed": state.get(
694:                   "app:total_caa_queries_executed", 0
695:               ),
696:           },
697:       },
698:       "memory_object_long_term": {
699:           "memory_search_query": memory_search_query,
700:           "in_memory_service_matches_count": len(matched_memories),
701:           "in_memory_service_matches": matched_memories[:5],
702:           "persistent_disk_sessions_saved": len(store.get("sessions", {})),
703:           "persistent_explicit_memories_saved": len(
704:               store.get("explicit_memories", [])
705:           ),
706:           "persistent_file_path": str(_PERSISTENT_MEMORY_FILE),
707:       },
708:   }
709: 
```

### Line-by-Line 상세 해설 (`L525 ~ L709`)
- **`L528–L619` (`save_user_preference_and_memory`)**:
  - `L528–L547`: 사용자가 자신의 직무(`role`), 담당 부서(`focus_department`), 관심 마케팅 채널(`focus_channel`), 중점 KPI 목록(`preferred_kpis_csv`), 또는 향후 Session에서도 기억해야 할 비즈니스 Insight(`key_insight_to_remember`)를 말했을 때 Root Agent나 Sub-Agent가 호출하는 비동기 Tool입니다.
  - `L558–L575`: 전달된 Argument 중 비어 있지 않은 항목만 골라 `tool_context.state["user:profile"]` 및 `tool_context.state["user:preferred_kpis"]`를 Update합니다.
  - `L585–L593`: `key_insight_to_remember`가 입력된 경우 Timestamp와 함께 `tool_context.state["user:pinned_insights"]`에 추가(최대 20건)합니다.
  - `L597–L611`: 변경된 `user:*` State와 명시적 기억(`explicit_memories`)을 `.adk/long_term_memory_bank.json`에 즉시 저장하고 `_sync_store_into_adk_memory_service(...)`로 `MemoryService`에 반영합니다.
- **`L622–L709` (`inspect_session_and_memory_status`)**:
  - `L622–L645`: 사용자가 현재 Session의 4-Scope State 상태나 과거 Long-Term Memory를 점검해 달라고 요청할 때 호출되는 진단 Tool입니다.
  - `L648–L660` (`await tool_context.search_memory(memory_search_query)`): ADK `ToolContext`가 제공하는 표준 `search_memory()` Method를 호출하여 `MemoryService`에 Indexing된 과거 Session 이력 및 Insight를 Keyword로 검색합니다.
  - `L662–L708`:
    - `session_object` (`L664–L672`): 현재 `session.id`, `session.app_name`, `session.user_id`, 현재 Session의 총 Event 개수(`len(session.events)`), `session_turn_count`, `active_domain` 반환
    - `state_scopes` (`L673–L697`): `1_temp_scope`, `2_session_scope`, `3_user_scope`, `4_app_scope`의 실시간 저장 값 반환
    - `memory_object_long_term` (`L698–L707`): `MemoryService` 검색 매칭 건수(`in_memory_service_matches_count`), 매칭된 기억 미리보기, 그리고 `.adk/long_term_memory_bank.json`에 영속 저장된 총 Session/Memory 개수를 반환합니다.

---

## Part 8. 3개 Domain Sub-Agent 전용 Tool Functions (`L711 ~ L805`)

```python
711: # ==============================================================================
712: # Sub-Agent 1 Tools: Customer CRM & Marketing Funnel (`thelook_customer_marketing_ca`)
713: # ==============================================================================
714: def ask_customer_marketing_caa(
715:     query: str,
716:     tool_context: ToolContext | None = None,
717: ) -> dict[str, Any]:
718:   """Queries BigQuery CAA Sub-Agent #1 (`thelook_customer_marketing_ca`) for Customer & Marketing analytics.
719: 
720:   Target Tables: `users`, `events`, `orders`, `order_items`
721:   Domain KPIs: VIP 고객, 이탈/휴면 고객, 신규 가입 고객, 유입 경로(traffic_source), 장바구니 포기율(이탈율), 객단가(AOV)/ARPU.
722: 
723:   Args:
724:       query: Standalone natural-language analytical question in Korean or English.
725:   """
726:   return _query_domain_caa_agent(
727:       agent_id=CUSTOMER_MARKETING_CA_ID,
728:       domain_label="Domain 1: Customer CRM & Marketing Funnel",
729:       query=query,
730:       tool_context=tool_context,
731:   )
732: 
733: 
734: def get_customer_marketing_caa_info() -> dict[str, Any]:
735:   """Returns metadata, connected BigQuery tables, and system instruction of `thelook_customer_marketing_ca`."""
736:   return data_agent_tool.get_data_agent_info(
737:       data_agent_name=CUSTOMER_MARKETING_CA_RESOURCE,
738:       credentials=_get_cloud_platform_adc(),
739:       settings=_TOOL_SETTINGS,
740:   )
741: 
742: 
743: # ==============================================================================
744: # Sub-Agent 2 Tools: Product, Margin & Return Analytics (`thelook_product_profitability_ca`)
745: # ==============================================================================
746: def ask_product_profitability_caa(
747:     query: str,
748:     tool_context: ToolContext | None = None,
749: ) -> dict[str, Any]:
750:   """Queries BigQuery CAA Sub-Agent #2 (`thelook_product_profitability_ca`) for Product, Margin & Return analytics.
751: 
752:   Target Tables: `products`, `order_items`, `orders`
753:   Domain KPIs: 상품 마진율, 실판매 마진액/순매출액, 반품/취소 건, 취소/반품 비율(환불률), 부서/카테고리/브랜드 수익성.
754: 
755:   Args:
756:       query: Standalone natural-language analytical question in Korean or English.
757:   """
758:   return _query_domain_caa_agent(
759:       agent_id=PRODUCT_PROFITABILITY_CA_ID,
760:       domain_label="Domain 2: Product, Profitability & Return Analytics",
761:       query=query,
762:       tool_context=tool_context,
763:   )
764: 
765: 
766: def get_product_profitability_caa_info() -> dict[str, Any]:
767:   """Returns metadata, connected BigQuery tables, and system instruction of `thelook_product_profitability_ca`."""
768:   return data_agent_tool.get_data_agent_info(
769:       data_agent_name=PRODUCT_PROFITABILITY_CA_RESOURCE,
770:       credentials=_get_cloud_platform_adc(),
771:       settings=_TOOL_SETTINGS,
772:   )
773: 
774: 
775: # ==============================================================================
776: # Sub-Agent 3 Tools: Supply Chain, Inventory & Logistics (`thelook_supply_chain_ca`)
777: # ==============================================================================
778: def ask_supply_chain_logistics_caa(
779:     query: str,
780:     tool_context: ToolContext | None = None,
781: ) -> dict[str, Any]:
782:   """Queries BigQuery CAA Sub-Agent #3 (`thelook_supply_chain_ca`) for Supply Chain, Inventory & Fulfillment analytics.
783: 
784:   Target Tables: `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`
785:   Domain KPIs: 물류 센터(DC/창고), 평균 배송 소요 시간(배송 리드타임), 출고 준비 리드타임, 미판매 재고율(sold_at IS NULL), 재고 원가 총액.
786: 
787:   Args:
788:       query: Standalone natural-language analytical question in Korean or English.
789:   """
790:   return _query_domain_caa_agent(
791:       agent_id=SUPPLY_CHAIN_CA_ID,
792:       domain_label="Domain 3: Supply Chain, Inventory & Logistics",
793:       query=query,
794:       tool_context=tool_context,
795:   )
796: 
797: 
798: def get_supply_chain_logistics_caa_info() -> dict[str, Any]:
799:   """Returns metadata, connected BigQuery tables, and system instruction of `thelook_supply_chain_ca`."""
800:   return data_agent_tool.get_data_agent_info(
801:       data_agent_name=SUPPLY_CHAIN_CA_RESOURCE,
802:       credentials=_get_cloud_platform_adc(),
803:       settings=_TOOL_SETTINGS,
804:   )
805: 
```

### Line-by-Line 상세 해설 (`L711 ~ L805`)
- **설계 원리 — 왜 범용 Function 1개 대신 Domain별 전용 Function 3개(`ask_customer_marketing_caa`, `ask_product_profitability_caa`, `ask_supply_chain_logistics_caa`)로 분리했는가?**:
  - 만약 Sub-Agent에게 `agent_id`를 직접 Argument로 입력받는 범용 Function을 주면, LLM이 간혹 잘못된 `agent_id`를 넣거나 권한 밖의 다른 Domain CAA를 호출할 위험이 있습니다.
  - 반면 각 Function 내부에서 `agent_id=CUSTOMER_MARKETING_CA_ID`처럼 **대상 CAA Resource ID를 Code Level에서 고정(Hard-Pinning)**하고 해당 Sub-Agent에게만 부여하면, **Sub-Agent 1은 물리적으로 오직 `thelook_customer_marketing_ca`만 호출**할 수 있어 100% 결정론적(Deterministic)인 Domain 격리가 달성됩니다.
- **`L714–L740` (Domain 1 전용 Tool)**:
  - `L714–L731` (`ask_customer_marketing_caa`): `thelook_customer_marketing_ca` (`users`, `events`, `orders`, `order_items`) 질의 실행
  - `L734–L740` (`get_customer_marketing_caa_info`): `thelook_customer_marketing_ca`의 GDA Metadata 조회
- **`L746–L772` (Domain 2 전용 Tool)**:
  - `L746–L763` (`ask_product_profitability_caa`): `thelook_product_profitability_ca` (`products`, `order_items`, `orders`) 질의 실행
  - `L766–L772` (`get_product_profitability_caa_info`): `thelook_product_profitability_ca`의 GDA Metadata 조회
- **`L778–L804` (Domain 3 전용 Tool)**:
  - `L778–L795` (`ask_supply_chain_logistics_caa`): `thelook_supply_chain_ca` (`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`) 질의 실행
  - `L798–L804` (`get_supply_chain_logistics_caa_info`): `thelook_supply_chain_ca`의 GDA Metadata 조회

---

## Part 9. Root Router 전용 Tool 및 동적 State 주입 Template (`L807 ~ L949`)

```python
807: # ==============================================================================
808: # Root Router Tools: Architecture Registry & Parallel Cross-Domain Synthesis
809: # ==============================================================================
810: def list_domain_caa_registry() -> dict[str, Any]:
811:   """Returns the 3 Domain-Scoped BigQuery CAA Sub-Agents registry, mapped tables, and Business Glossary KPIs."""
812:   return {
813:       "project_id": PROJECT_ID,
814:       "dataset": f"{PROJECT_ID}.{DATASET_ID}",
815:       "architecture": "Hierarchical Root Router + 3 Domain-Scoped BigQuery CAA Sub-Agents (with Session & Memory Bank)",
816:       "sub_agents": [
817:           {
818:               "sub_agent_name": "customer_marketing_subagent",
819:               "caa_data_agent": CUSTOMER_MARKETING_CA_RESOURCE,
820:               "domain": "고객 CRM & 마케팅 퍼널 분석 (Customer & Marketing)",
821:               "tables": ["users", "events", "orders", "order_items"],
822:               "business_glossary_kpis": [
823:                   "VIP 고객 (누적 구매액 >= $500 OR 주문건수 >= 5회)",
824:                   "이탈/휴면 고객 (최근 90일 이내 무주문)",
825:                   "신규 가입 고객 (최근 30일 이내 가입)",
826:                   "유입 경로 (users.traffic_source)",
827:                   "장바구니 포기율 (cart 세션 중 미구매 비율 %)",
828:                   "객단가 (AOV) 및 인당 평균 매출 (ARPU)",
829:               ],
830:           },
831:           {
832:               "sub_agent_name": "product_profitability_subagent",
833:               "caa_data_agent": PRODUCT_PROFITABILITY_CA_RESOURCE,
834:               "domain": "상품·카테고리 수익성 & 반품 분석 (Product & Profitability)",
835:               "tables": ["products", "order_items", "orders"],
836:               "business_glossary_kpis": [
837:                   "상품 마진율 ((retail_price - cost) / retail_price * 100)",
838:                   "실판매 마진액 (Realized Gross Profit) 및 순매출액 (Net Revenue)",
839:                   "반품/취소 건 (status IN ('Returned', 'Cancelled'))",
840:                   "취소/반품 비율 (환불률 %)",
841:                   "부서(department) / 카테고리(category) / 브랜드(brand) 수익성",
842:               ],
843:           },
844:           {
845:               "sub_agent_name": "supply_chain_logistics_subagent",
846:               "caa_data_agent": SUPPLY_CHAIN_CA_RESOURCE,
847:               "domain": "물류 센터·재고·배송 리드타임 분석 (Supply Chain & Logistics)",
848:               "tables": [
849:                   "distribution_centers",
850:                   "inventory_items",
851:                   "order_items",
852:                   "orders",
853:                   "products",
854:               ],
855:               "business_glossary_kpis": [
856:                   "물류 센터 (distribution_centers / 창고 / DC)",
857:                   "평균 배송 소요 시간 (TIMESTAMP_DIFF(delivered_at, shipped_at, DAY/HOUR))",
858:                   "출고 준비 리드타임 (TIMESTAMP_DIFF(shipped_at, created_at, HOUR))",
859:                   "미판매 재고율 (inventory_items.sold_at IS NULL 비율 %)",
860:                   "미판매 재고 원가 총액 (SUM(cost) WHERE sold_at IS NULL)",
861:               ],
862:           },
863:       ],
864:   }
865: 
866: 
867: def run_cross_domain_caa_analysis(
868:     customer_marketing_query: str = "",
869:     product_profitability_query: str = "",
870:     supply_chain_logistics_query: str = "",
871:     tool_context: ToolContext | None = None,
872: ) -> dict[str, Any]:
873:   """Executes multiple domain-scoped BigQuery CAA Data Agents in parallel for cross-domain composite questions.
874: 
875:   Use this tool ONLY when the user's question spans 2 or more domains simultaneously
876:   (e.g., asking for Customer VIP metrics + Product Margin/Refund metrics + Logistics DC Delivery metrics together).
877:   Leave a domain's query empty (`""`) if that domain is not needed.
878: 
879:   Args:
880:       customer_marketing_query: Question for `thelook_customer_marketing_ca` (or empty string).
881:       product_profitability_query: Question for `thelook_product_profitability_ca` (or empty string).
882:       supply_chain_logistics_query: Question for `thelook_supply_chain_ca` (or empty string).
883:   """
884:   tasks: list[tuple[str, str, str]] = []
885:   if customer_marketing_query.strip():
886:     tasks.append((
887:         CUSTOMER_MARKETING_CA_ID,
888:         "Domain 1: Customer CRM & Marketing Funnel",
889:         customer_marketing_query.strip(),
890:     ))
891:   if product_profitability_query.strip():
892:     tasks.append((
893:         PRODUCT_PROFITABILITY_CA_ID,
894:         "Domain 2: Product, Profitability & Return Analytics",
895:         product_profitability_query.strip(),
896:     ))
897:   if supply_chain_logistics_query.strip():
898:     tasks.append((
899:         SUPPLY_CHAIN_CA_ID,
900:         "Domain 3: Supply Chain, Inventory & Logistics",
901:         supply_chain_logistics_query.strip(),
902:     ))
903: 
904:   if not tasks:
905:     return {"status": "NO_QUERIES_PROVIDED"}
906: 
907:   results: dict[str, Any] = {}
908:   with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
909:     future_map = {
910:         pool.submit(_query_domain_caa_agent, agent_id, label, q, None): (
911:             agent_id,
912:             label,
913:             q,
914:         )
915:         for agent_id, label, q in tasks
916:     }
917:     for fut, (agent_id, label, q) in future_map.items():
918:       res = fut.result()
919:       results[label] = res
920:       if tool_context is not None and res.get("status") == "SUCCESS":
921:         _record_caa_result_into_session_state(
922:             state=tool_context.state,
923:             agent_id=agent_id,
924:             domain_label=f"Cross-Domain ({label})",
925:             data_agent_name=res.get("data_agent", ""),
926:             query=q,
927:             generated_sql=res.get("generated_sql", ""),
928:             rows=[],
929:             ca_final_answer=res.get("ca_final_answer", ""),
930:             session_id=tool_context.session.id,
931:             user_id=tool_context.user_id or "default_user",
932:         )
933: 
934:   return {
935:       "status": "SUCCESS",
936:       "executed_domains": len(tasks),
937:       "domain_results": results,
938:   }
939: 
940: 
941: _SHARED_SESSION_MEMORY_CONTEXT = """
942: ### [현재 ADK Session State 및 사용자 장기 기억 컨텍스트]
943: - **사용자 프로필 (`user:profile`)**: {user:profile?}
944: - **사용자 중점 관리 KPI (`user:preferred_kpis`)**: {user:preferred_kpis?}
945: - **저장된 핵심 인사이트 (`user:pinned_insights`)**: {user:pinned_insights?}
946: - **현재 세션 누적 분석 턴 수 (`session_turn_count`)**: {session_turn_count?}
947: - **최근 도메인 분석 이력 (`domain_query_history`)**: {domain_query_history?}
948: """
949: 
```

### Line-by-Line 상세 해설 (`L807 ~ L949`)
- **`L810–L864` (`list_domain_caa_registry`)**: 사용자가 *"현재 구성된 3개 Sub-Agent와 담당 Table 및 비즈니스 용어를 보여줘"*라고 질문했을 때, BigQuery 과금이나 불필요한 API 호출 없이 즉시 3개 Sub-Agent의 매핑 정보를 반환하는 Root 전용 Function입니다.
- **`L867–L938` (`run_cross_domain_caa_analysis` — 복합 Domain 병렬 Fan-out Engine)**:
  - `L868–L870`: 3개 Domain 각각의 하위 질문(`customer_marketing_query`, `product_profitability_query`, `supply_chain_logistics_query`)을 Optional 문자열 Parameter로 받습니다. Root LLM이 사용자의 복합 질문을 분석하여 필요한 Domain Parameter에만 하위 질문을 채워서 호출합니다(Query Decomposition).
  - `L884–L905`: 비어 있지 않은 Domain 질문만 `tasks` List에 담습니다.
  - `L908–L918` (`ThreadPoolExecutor` 병렬 실행):
    - 주의할 점으로, Worker Thread 내부(`pool.submit`)에서는 `tool_context`를 `None`으로 전달하여 여러 Thread가 동시에 `tool_context.state`를 수정하는 Race Condition(경합 조건)을 방지합니다.
    - 이후 Main Thread(`L917–L932`)에서 `fut.result()`를 순서대로 수거한 뒤 `_record_caa_result_into_session_state`를 호출하여 Thread-Safe하게 `tool_context.state`를 Update합니다.
- **`L941–L948` (`_SHARED_SESSION_MEMORY_CONTEXT` — ADK 동적 State Interpolation)**:
  - Google ADK `LlmAgent`의 `instruction` 문자열 안에 **`{state_key?}`** 문법을 넣으면, ADK의 `instructions_llm_request_processor`가 매 Turn LLM을 호출할 때 `ctx.session.state["state_key"]`의 최신 값을 자동으로 치환(Interpolation)해 줍니다 (`?` 접미사는 해당 Key가 없을 때 `KeyError` 대신 빈 문자열로 안전하게 처리하라는 ADK 문법입니다).
  - 이를 통해 Root Agent와 3개 Sub-Agent 모두가 매 Turn **`user:profile`**, **`user:preferred_kpis`**, **`user:pinned_insights`**, **`session_turn_count`**, **`domain_query_history`**를 실시간으로 공유합니다.

---

## Part 10. 3개 Domain Sub-Agents 및 Root Router Agent 선언 (`L951 ~ L1119`)

```python
951: # ==============================================================================
952: # 3 Domain-Scoped ADK Sub-Agents
953: # ==============================================================================
954: customer_marketing_subagent = LlmAgent(
955:     model="gemini-2.5-flash",
956:     name="customer_marketing_subagent",
957:     description=(
958:         "Sub-Agent #1 for Customer CRM & Marketing Funnel analytics via BigQuery CAA "
959:         f"(`{CUSTOMER_MARKETING_CA_ID}`). Handles VIP customers, churn/dormant users, new signups, "
960:         "traffic_source performance, cart abandonment rate, AOV, and ARPU on `users`, `events`, `orders`, `order_items`."
961:     ),
962:     instruction=(
963:         "당신은 **고객 CRM 및 마케팅 퍼널 분석 전담 서브 에이전트(`customer_marketing_subagent`)**입니다.\n"
964:         f"- 전담 BigQuery CAA 리소스: `{CUSTOMER_MARKETING_CA_RESOURCE}`\n"
965:         "- 연결된 테이블 (4개): `users`, `events`, `orders`, `order_items`\n"
966:         "- 담당 핵심 지표: VIP 고객(우수 고객), 이탈/휴면 고객, 신규 가입 고객, 유입 경로(`traffic_source`), 장바구니 포기율(이탈율), 객단가(AOV), ARPU\n"
967:         + _SHARED_SESSION_MEMORY_CONTEXT
968:         + "\n[수행 지침]\n"
969:         "1. 고객/마케팅 관련 데이터 질문이 들어오면 반드시 `ask_customer_marketing_caa(query=...)` 도구를 호출하세요.\n"
970:         "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 구체적인 조건으로 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
971:         "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
972:         "3. 만약 사용자의 후속 질문이 **상품 마진율/반품/카테고리 수익성** 도메인이라면 `product_profitability_subagent`로 제어권을 이관(`transfer_to_agent`)하고, "
973:         "**물류센터/배송 소요 시간/미판매 재고** 도메인이라면 `supply_chain_logistics_subagent`로 이관하며, "
974:         "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
975:         "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) 마케팅 비즈니스 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
976:     ),
977:     tools=[
978:         preload_memory,
979:         load_memory,
980:         ask_customer_marketing_caa,
981:         get_customer_marketing_caa_info,
982:         save_user_preference_and_memory,
983:         inspect_session_and_memory_status,
984:     ],
985:     before_agent_callback=_initialize_session_and_rehydrate_memory,
986:     after_agent_callback=_save_session_to_long_term_memory,
987: )
988: 
989: product_profitability_subagent = LlmAgent(
990:     model="gemini-2.5-flash",
991:     name="product_profitability_subagent",
992:     description=(
993:         "Sub-Agent #2 for Product Merchandising, Gross Margin & Return/Refund analytics via BigQuery CAA "
994:         f"(`{PRODUCT_PROFITABILITY_CA_ID}`). Handles product margin %, net revenue, realized gross profit, "
995:         "return/cancellation rates (환불률), and category/brand/department profitability on `products`, `order_items`, `orders`."
996:     ),
997:     instruction=(
998:         "당신은 **상품·카테고리 수익성 및 반품 분석 전담 서브 에이전트(`product_profitability_subagent`)**입니다.\n"
999:         f"- 전담 BigQuery CAA 리소스: `{PRODUCT_PROFITABILITY_CA_RESOURCE}`\n"
1000:         "- 연결된 테이블 (3개): `products`, `order_items`, `orders`\n"
1001:         "- 담당 핵심 지표: 상품 마진율(`(retail_price - cost)/retail_price * 100`), 순매출액(Net Revenue), 실판매 마진액(Gross Profit), 반품/취소 건, 취소/반품 비율(환불률), 카테고리/브랜드/부서별 수익성\n"
1002:         + _SHARED_SESSION_MEMORY_CONTEXT
1003:         + "\n[수행 지침]\n"
1004:         "1. 상품/마진/환불/카테고리 매출 관련 질문이 들어오면 반드시 `ask_product_profitability_caa(query=...)` 도구를 호출하세요.\n"
1005:         "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
1006:         "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
1007:         "3. 만약 사용자의 후속 질문이 **고객 세그먼트(VIP/휴면)/유입 경로/장바구니 이탈율** 도메인이라면 `customer_marketing_subagent`로 이관(`transfer_to_agent`)하고, "
1008:         "**물류센터/배송 소요 시간/미판매 재고** 도메인이라면 `supply_chain_logistics_subagent`로 이관하며, "
1009:         "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
1010:         "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) 상품/수익성 MD 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
1011:     ),
1012:     tools=[
1013:         preload_memory,
1014:         load_memory,
1015:         ask_product_profitability_caa,
1016:         get_product_profitability_caa_info,
1017:         save_user_preference_and_memory,
1018:         inspect_session_and_memory_status,
1019:     ],
1020:     before_agent_callback=_initialize_session_and_rehydrate_memory,
1021:     after_agent_callback=_save_session_to_long_term_memory,
1022: )
1023: 
1024: supply_chain_logistics_subagent = LlmAgent(
1025:     model="gemini-2.5-flash",
1026:     name="supply_chain_logistics_subagent",
1027:     description=(
1028:         "Sub-Agent #3 for Supply Chain, Inventory & Fulfillment Lead-Time analytics via BigQuery CAA "
1029:         f"(`{SUPPLY_CHAIN_CA_ID}`). Handles distribution centers (물류센터/DC), average delivery lead time (평균 배송 소요 시간), "
1030:         "order-to-ship time, unsold inventory rate (미판매 재고율), and inventory holding cost on "
1031:         "`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`."
1032:     ),
1033:     instruction=(
1034:         "당신은 **물류·재고·배송 리드타임(SCM) 분석 전담 서브 에이전트(`supply_chain_logistics_subagent`)**입니다.\n"
1035:         f"- 전담 BigQuery CAA 리소스: `{SUPPLY_CHAIN_CA_RESOURCE}`\n"
1036:         "- 연결된 테이블 (5개): `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`\n"
1037:         "- 담당 핵심 지표: 물류 센터(창고/DC), 평균 배송 소요 시간(`TIMESTAMP_DIFF(delivered_at, shipped_at, DAY)`), 출고 준비 리드타임, 미판매 재고율(`sold_at IS NULL`), 미판매 재고 원가 총액\n"
1038:         + _SHARED_SESSION_MEMORY_CONTEXT
1039:         + "\n[수행 지침]\n"
1040:         "1. 물류센터/배송 리드타임/재고 관련 질문이 들어오면 반드시 `ask_supply_chain_logistics_caa(query=...)` 도구를 호출하세요.\n"
1041:         "   - 이전 대화 맥락(`domain_query_history`)이나 사용자 선호 설정(`user:profile`)을 참고하여 대명사를 풀어쓴 **완결된 문장(Standalone Query)**으로 변환하여 `query`에 전달하세요.\n"
1042:         "2. 사용자가 분석 선호도나 인사이트를 기억해 달라고 하면 `save_user_preference_and_memory(...)`를 호출하고, 과거 세션 기억 조회가 필요하면 `load_memory` 또는 `inspect_session_and_memory_status`를 호출하세요.\n"
1043:         "3. 만약 사용자의 후속 질문이 **고객(VIP/휴면)/유입 경로/장바구니 퍼널** 도메인이라면 `customer_marketing_subagent`로 이관(`transfer_to_agent`)하고, "
1044:         "**상품 마진율/반품/카테고리 수익성** 도메인이라면 `product_profitability_subagent`로 이관하며, "
1045:         "복합 도메인 질문이나 전체 세션/메모리 점검 질문이라면 `thelook_enterprise_root_router`로 이관하세요.\n"
1046:         "4. 응답 시 **(1) 호출된 도메인 CAA 에이전트 ID**, **(2) 생성된 SQL(`generated_sql`)**, **(3) 조회 결과 데이터 표(`markdown_table`)**, **(4) SCM/물류 최적화 인사이트 요약**을 마크다운으로 깔끔하게 제시하세요."
1047:     ),
1048:     tools=[
1049:         preload_memory,
1050:         load_memory,
1051:         ask_supply_chain_logistics_caa,
1052:         get_supply_chain_logistics_caa_info,
1053:         save_user_preference_and_memory,
1054:         inspect_session_and_memory_status,
1055:     ],
1056:     before_agent_callback=_initialize_session_and_rehydrate_memory,
1057:     after_agent_callback=_save_session_to_long_term_memory,
1058: )
1059: 
1060: 
1061: # ==============================================================================
1062: # Root Agent: Enterprise Multi-Domain Router & Session/Memory Orchestrator
1063: # ==============================================================================
1064: root_agent = LlmAgent(
1065:     model="gemini-2.5-flash",
1066:     name="thelook_enterprise_root_router",
1067:     description=(
1068:         "Enterprise Root Router Agent orchestrating 3 Domain-Scoped BigQuery CAA Sub-Agents "
1069:         "(`customer_marketing_subagent`, `product_profitability_subagent`, `supply_chain_logistics_subagent`) "
1070:         f"with 4-Scope Session State and Long-Term Memory Bank on `{PROJECT_ID}.{DATASET_ID}`."
1071:     ),
1072:     instruction=(
1073:         f"당신은 `{PROJECT_ID}.{DATASET_ID}` 데이터 레이크의 **엔터프라이즈 멀티 에이전트 루트 라우터(`thelook_enterprise_root_router`)**입니다.\n"
1074:         "하위에 도메인별로 테이블 범위(Table Scope)와 비즈니스 용어집(Business Glossary)이 분리된 **3개의 BigQuery CAA 전문 서브 에이전트(Sub-Agents)**를 거느리고 있으며, "
1075:         "**ADK Session Object(4-Scope State + Multi-Turn History)** 및 **ADK Memory Object(세션 간 장기 기억)**를 통합 관리합니다.\n"
1076:         + _SHARED_SESSION_MEMORY_CONTEXT
1077:         + "\n### [하위 3대 BigQuery CAA 서브 에이전트 구성]\n"
1078:         "1. **`customer_marketing_subagent` (고객 CRM & 마케팅 퍼널)**\n"
1079:         f"   - BQ CAA 에이전트: `{CUSTOMER_MARKETING_CA_RESOURCE}`\n"
1080:         "   - 담당 테이블: `users`, `events`, `orders`, `order_items`\n"
1081:         "   - 핵심 질문: VIP/우수 고객, 이탈/휴면 고객, 신규 가입 고객, 유입 경로(`traffic_source`), 장바구니 포기율(이탈율), 객단가(AOV)\n"
1082:         "2. **`product_profitability_subagent` (상품·카테고리 수익성 & 반품)**\n"
1083:         f"   - BQ CAA 에이전트: `{PRODUCT_PROFITABILITY_CA_RESOURCE}`\n"
1084:         "   - 담당 테이블: `products`, `order_items`, `orders`\n"
1085:         "   - 핵심 질문: 상품 마진율, 순매출액/실판매 마진액, 반품/취소 건, 취소/반품 비율(환불률), 카테고리/브랜드/부서별 수익성\n"
1086:         "3. **`supply_chain_logistics_subagent` (물류 센터·재고·배송 리드타임)**\n"
1087:         f"   - BQ CAA 에이전트: `{SUPPLY_CHAIN_CA_RESOURCE}`\n"
1088:         "   - 담당 테이블: `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`\n"
1089:         "   - 핵심 질문: 물류 센터(DC/창고)별 성과, 평균 배송 소요 시간(리드타임), 출고 소요일, 미판매 재고율(`sold_at IS NULL`), 재고 원가 총액\n\n"
1090:         "### [라우팅 및 세션/메모리 관리 규칙]\n"
1091:         "1. **사용자 선호도 설정 / 인사이트 기억 요청**:\n"
1092:         "   - 사용자가 본인의 역할/직무, 관심 부서(예: `Women`), 관심 채널, 중점 관리 KPI를 알려주거나 특정 분석 결과를 기억해 달라고 요청하면 `save_user_preference_and_memory(...)` 도구를 호출하여 `user:*` State와 장기 기억(`MemoryService`)에 저장하세요.\n"
1093:         "2. **세션 상태(`Session`) 및 장기 기억(`Memory`) 점검/복원 요청**:\n"
1094:         "   - 사용자가 '현재 세션 상태와 메모리 상태를 보여줘' 또는 '지난 세션에서 내가 어떤 분석을 했었지?'라고 물으면 `inspect_session_and_memory_status(...)` 및 `load_memory(...)` 도구를 호출하여 4단계 State 스코프(`temp:`, `session`, `user:`, `app:`)와 장기 기억 검색 결과를 상세히 브리핑하세요.\n"
1095:         "3. **아키텍처/에이전트 구성 확인 질문**:\n"
1096:         "   - `list_domain_caa_registry()`를 호출하여 3개 서브 에이전트의 도메인·테이블·용어집 구성을 표로 설명하세요.\n"
1097:         "4. **단일 도메인 질문 (Single-Domain Routing)**:\n"
1098:         "   - 고객/마케팅/트래픽/장바구니 → `customer_marketing_subagent`로 `transfer_to_agent` 호출\n"
1099:         "   - 상품/마진/환불률/카테고리/브랜드 → `product_profitability_subagent`로 `transfer_to_agent` 호출\n"
1100:         "   - 물류센터/배송시간/재고 → `supply_chain_logistics_subagent`로 `transfer_to_agent` 호출\n"
1101:         "5. **복합 도메인 질문 (Cross-Domain Executive Query)**:\n"
1102:         "   - 한 질문 안에 2개 이상의 도메인 지표가 동시에 포함된 경우 `run_cross_domain_caa_analysis(...)` 도구를 호출하여 병렬 실행 후 종합 리포트를 작성하세요."
1103:     ),
1104:     sub_agents=[
1105:         customer_marketing_subagent,
1106:         product_profitability_subagent,
1107:         supply_chain_logistics_subagent,
1108:     ],
1109:     tools=[
1110:         preload_memory,
1111:         load_memory,
1112:         list_domain_caa_registry,
1113:         run_cross_domain_caa_analysis,
1114:         save_user_preference_and_memory,
1115:         inspect_session_and_memory_status,
1116:     ],
1117:     before_agent_callback=_initialize_session_and_rehydrate_memory,
1118:     after_agent_callback=_save_session_to_long_term_memory,
1119: )
```

### Line-by-Line 상세 해설 (`L951 ~ L1119`)

#### 10.1 Sub-Agent #1: `customer_marketing_subagent` (`L954 ~ L987`)
- **`L955` (`model="gemini-2.5-flash"`)**: 빠르고 정확한 Tool Calling 및 요약 생성을 위해 Vertex AI `gemini-2.5-flash` Model을 사용합니다.
- **`L956–L961` (`name`, `description`)**:
  - **핵심 Routing 근거**: ADK Runtime(`agent_transfer.py`)은 Parent(`root_agent`)와 Peer Sub-Agent들의 System Prompt에 이 `name`과 `description`을 자동으로 주입하여 `transfer_to_agent` 호출 기준점으로 삼습니다. 따라서 담당 CAA ID, 담당 KPI(VIP, 휴면, 신규 가입, 유입 경로, 장바구니 포기율, AOV, ARPU), 담당 Table 4개를 명확히 기술했습니다.
- **`L962–L976` (`instruction`)**:
  - `L967`: `_SHARED_SESSION_MEMORY_CONTEXT`를 결합하여 현재 사용자의 선호 부서/채널 및 이전 대화 이력을 참조하게 합니다.
  - `L970` (Standalone Query 재작성 지침): 사용자가 *"그중에서 상위 3개만"*이라고 질문했을 때 대명사를 그대로 CAA에 넘기지 않고, `domain_query_history`와 `user:profile`을 참고해 완결된 문장으로 풀어서 `ask_customer_marketing_caa(query=...)`를 호출하도록 지시합니다.
  - `L972–L974` (Peer-to-Peer & Parent Transfer 지침): 후속 질문이 타 Domain(상품 마진/환불률 또는 물류/배송)이면 해당 Peer Sub-Agent로, 복합 Domain 질문이면 Root Agent로 즉시 `transfer_to_agent`를 호출하도록 지시합니다.
- **`L977–L984` (`tools`)**: Long-Term Memory Tool(`preload_memory`, `load_memory`), Domain 1 전용 CAA Tool(`ask_customer_marketing_caa`, `get_customer_marketing_caa_info`), Session/Memory 관리 Tool 2종만 부여합니다.
- **`L985–L986` (`before_agent_callback`, `after_agent_callback`)**: Sub-Agent가 현재 Active Agent로 직접 다음 Turn 질문을 받을 때에도 동일하게 Session 초기화 및 Long-Term Memory 영속화가 수행되도록 양쪽 Callback을 모두 등록합니다.

#### 10.2 Sub-Agent #2: `product_profitability_subagent` (`L989 ~ L1022`)
- **`L989–L1022`**:
  - `thelook_product_profitability_ca` (`products`, `order_items`, `orders` 3개 Table Scoping) 전담 Sub-Agent입니다.
  - 전용 Tool로 `ask_product_profitability_caa`와 `get_product_profitability_caa_info`만 보유하며, 상품 마진율(`(retail_price - cost)/retail_price * 100`), 순매출액, 실판매 마진액, 취소/반품 비율(환불률) 분석을 전담합니다.

#### 10.3 Sub-Agent #3: `supply_chain_logistics_subagent` (`L1024 ~ L1058`)
- **`L1024–L1058`**:
  - `thelook_supply_chain_ca` (`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products` 5개 Table Scoping) 전담 Sub-Agent입니다.
  - 전용 Tool로 `ask_supply_chain_logistics_caa`와 `get_supply_chain_logistics_caa_info`만 보유하며, 물류센터(DC)별 평균 배송 소요 시간(`TIMESTAMP_DIFF(delivered_at, shipped_at, DAY)`), 출고 Lead Time, 미판매 재고율(`sold_at IS NULL`) 분석을 전담합니다.

#### 10.4 Root Router Agent: `root_agent` (`thelook_enterprise_root_router`, `L1064 ~ L1119`)
- **`L1064` (`root_agent = LlmAgent(...)`)**: Google ADK CLI(`adk web`, `adk run`)가 `bq_caa_3domain_multi_agent` Package를 Load할 때 Entrypoint로 찾는 필수 Variable명(`root_agent`)입니다.
- **`L1072–L1103` (`instruction` — 5대 의사결정 규칙)**:
  1. **규칙 1 (`L1091–L1092`)**: 사용자 Profile/선호 KPI/Insight 저장 요청 → `save_user_preference_and_memory` 호출
  2. **규칙 2 (`L1093–L1094`)**: Session State 및 Long-Term Memory 점검/복원 요청 → `inspect_session_and_memory_status` 및 `load_memory` 호출
  3. **규칙 3 (`L1095–L1096`)**: 전체 Agent/Table/Glossary 구성 질문 → `list_domain_caa_registry` 호출
  4. **규칙 4 (`L1097–L1100`)**: 단일 Domain 분석 질문 → ADK 내장 `transfer_to_agent`를 호출해 해당 Sub-Agent로 즉시 제어권 위임
  5. **규칙 5 (`L1101–L1102`)**: 2개 이상 Domain이 결합된 복합 질문 → `run_cross_domain_caa_analysis`를 호출해 병렬 실행 후 종합 Report 작성
- **`L1104–L1108` (`sub_agents=[...]`)**:
  - 이 List에 3개 Sub-Agent Object를 등록하는 순간, ADK 내부에서 다음 작업이 자동으로 일어납니다:
    1. 각 Sub-Agent의 `parent_agent` Pointer가 `root_agent`로 연결됩니다.
    2. `root_agent`와 각 Sub-Agent에게 `TransferToAgentTool`(`transfer_to_agent`)이 자동 주입되며, 허용된 Agent 이름 목록이 JSON Schema `enum`으로 강제됩니다.
- **`L1109–L1116` (`tools=[...]`)**: Root Agent는 개별 Domain CAA Tool(`ask_*_caa`)를 직접 갖지 **않고**(단일 Domain 질문 시 자신이 직접 호출하지 않고 반드시 담당 Sub-Agent로 `transfer_to_agent` 위임하도록 강제하기 위함), 오직 복합 Domain 병렬 분석 Tool(`run_cross_domain_caa_analysis`), Architecture Registry Tool(`list_domain_caa_registry`), 그리고 Session/Memory 관리 Tool(`preload_memory`, `load_memory`, `save_user_preference_and_memory`, `inspect_session_and_memory_status`)만 보유합니다.
- **`L1117–L1118` (`before_agent_callback`, `after_agent_callback`)**: 매 Turn 시작과 끝에 4-Scope `Session.state` 초기화/복원 및 `MemoryService` + `.adk/long_term_memory_bank.json` 영속화를 보장합니다.
