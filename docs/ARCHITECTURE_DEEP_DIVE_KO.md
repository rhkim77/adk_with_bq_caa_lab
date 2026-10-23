# [Technical Whitepaper] Google ADK + BigQuery CAA Multi-Agent Architecture 심층 해설
**(공식 Integration Pattern 분류 체계, Root-to-SubAgent Routing 및 ADK `Session Object` + `Memory Object` Architecture Pattern)**

---

## 0. 공식 문서의 Integration Pattern 분류 체계와 본 Repository의 위치

Google Cloud 공식 문서([Integration patterns for data agents](https://cloud.google.com/gemini/docs/conversational-analytics-api/integration-patterns) 및 [State management for data agents](https://cloud.google.com/gemini/docs/conversational-analytics-api/state-management))에서는 BQ CAA 연동 방식을 크게 **Direct API, ADK, MCP, A2A의 4대 통합 접근법(총 7개 세부 패턴)**과 **3가지 API Context Mode(`ConversationReference`, `DataAgentContext`, `InlineContext`)**로 정의하고 있습니다 (`[확인됨 / Verified]`).

본 Repository는 그중 엔터프라이즈 Multi-Agent 환경에서 Governance(Glossary/Verified Queries)가 보장되는 **핵심 패턴들(ADK `DataAgentToolset`, ADK `Custom Streaming Sub-Agent`, `Direct API Orchestrator`, `A2A`/`MCP`)**을 추려 비교할 수 있도록 구성되었으며, 여기에 실제 대규모 운영 시 발생하는 Token 비용 문제를 해결하기 위해 **ADK `Session`/`Memory` 기반의 경량 최적화 Best Practice**를 결합한 아키텍처입니다.

| 공식 문서의 4대 통합 접근법 | 공식 세부 패턴 | 본 Repository 내 대응 Package 및 구현 특징 |
| :--- | :--- | :--- |
| **1. Framework-driven Orchestration (ADK)** | • Governed with `DataAgentToolset` (`ask_data_agent`)<br/>• Custom streaming sub-agent (`ca-api-adk-streaming`) | • **`bq_caa_toolset_agent/`**: `ask_data_agent` 기반 Baseline vs Governed 비교 (`cloud-platform` Scope 주입)<br/>• **`bq_caa_streaming_agent/`**: `ConversationalAnalyticsStreamingAgent` (`BaseAgent`) + `temp:` State 후처리 연동 |
| **2. Direct API Integration & ADK Hybrid (권장)** | • Custom orchestrator + Stateless `DataAgentContext` | • **`bq_caa_3domain_multi_agent/` (Main Lab)**: ADK Root/Sub-Agent Routing 위에 정적 `agent_id` Binding(메타데이터 조회 제거), `[-6:]`(3 Turn) Sliding Window, `THOUGHT`/`PROGRESS` 제거 및 20행 Markdown 요약(Token Diet) 결합 |
| **3. Vertical (MCP) & 4. Horizontal (A2A)** | • `MCP within ADK` (`ToolboxToolset` / `McpToolset`)<br/>• `A2A Protocol` (`orchestrate-agents-a2a`) | • 다중 클라이언트/IDE 표준화 또는 이기종 에이전트 협업 필요 시 확장 적용 가능 (Gemini Enterprise는 별도 Publish 기능으로 연동) |

---

## 1. 왜 Single Agent가 아닌 `Root + 3 Domain-Scoped BQ CAA` Multi-Agent인가?

Enterprise Data Warehouse(수십~수백 개 Table, 수백 개 비즈니스 지표)를 단 하나의 BigQuery Conversational Analytics(CAA) Agent에 모두 연결하면 다음과 같은 **3가지 구조적 병목**이 발생합니다 (`[확인됨 / Verified]`):

1. **입력 Token 폭증 (Prompt Bloat & Cost Spike)**:
   - 단일 CAA Agent에 많은 Table과 방대한 System Instruction(Business Glossary 전체)을 연결하면, 매 질문마다 전체 Schema Metadata·Sample 값·Glossary가 내부 Prompt에 주입되어 **질문 1회당 수만~10만+ 입력 Token**이 소모됩니다.
2. **유사 Column 간 오조인 (Cross-Domain Schema Confusion)**:
   - 예를 들어 `users.created_at`(가입일), `orders.created_at`(주문일), `inventory_items.created_at`(입고일)이 한 Agent에 섞여 있으면 LLM이 "지난 달 신규 사용자의 주문"을 계산할 때 잘못된 Table의 날짜 Column을 `JOIN`할 확률이 높아집니다.
3. **복합 Domain 질문 시 거대 SQL Fan-out 오류**:
   - 사용자 Event(`events`, 수백만 Row), 주문 상세(`order_items`), 재고(`inventory_items`)를 단일 SQL Query에서 한 번에 `JOIN`하면 다대다(N:M) Cartesian Product(Fan-out)가 발생하여 집계 수치가 왜곡됩니다.

### 해결책: Domain별 Table Scoping + 계층형 ADK Orchestration

본 Architecture는 `thelook_ecommerce_agent` Dataset의 7개 Table과 10대 Business Glossary를 **3개의 독립된 Business Domain CAA Agent**로 분리하고, 상단에 **ADK Root Router Agent**를 배치합니다.

| Domain 구분 | ADK Sub-Agent 이름 | 연결된 BigQuery CAA Resource ID | Scoped Tables (최소 권한 원칙) | 전담 Business Glossary (SQL Mapping Rules) |
| :--- | :--- | :--- | :--- | :--- |
| **Domain 1<br/>(사용자 & 마케팅)** | `customer_marketing_subagent` | `thelook_customer_marketing_ca` | `users`, `events`, `orders`, `order_items` (4개) | VIP 사용자, 이탈/휴면 사용자, 신규 가입 사용자, 유입 경로(`traffic_source`), 장바구니 포기율, AOV/ARPU |
| **Domain 2<br/>(상품 & 수익성)** | `product_profitability_subagent` | `thelook_product_profitability_ca` | `products`, `order_items`, `orders` (3개) | 상품 마진율, 순매출액(Net Revenue), 실판매 마진액, 반품/취소 건, 취소/반품 비율(환불률) |
| **Domain 3<br/>(물류 & 재고)** | `supply_chain_logistics_subagent` | `thelook_supply_chain_ca` | `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products` (5개) | 물류 센터(DC/창고), 평균 배송 소요 시간(Lead Time), 출고 Lead Time, 미판매 재고율, 재고 원가 총액 |

---

## 2. Root Agent가 Sub-Agent(BQ CAA)를 Routing하는 내부 Logic 상세 해설

`bq_caa_3domain_multi_agent/agent.py`의 Routing은 질문의 성격에 따라 **3가지 경로(Path A / B / C)**로 작동하며, Google ADK Runtime(`google.adk.flows.llm_flows.agent_transfer`)의 내부 Mechanism과 긴밀하게 결합되어 있습니다 (`[확인됨 / Verified: agent_transfer.py & transfer_to_agent_tool.py]`).

```mermaid
flowchart TB
  USER(["사용자 자연어 질문 입력"]) --> ROOT["Root Agent<br/>(thelook_enterprise_root_router)"]

  ROOT -->|"1. 단일 Domain 질문<br/>transfer_to_agent(enum)"| HANDOFF{"Domain Intent 분류"}
  ROOT -->|"2. 복합 Domain 질문 (2+ Domains)<br/>run_cross_domain_caa_analysis()"| PARALLEL["ThreadPoolExecutor 병렬 호출"]
  ROOT -->|"3. Session/Long-Term Memory 점검 또는 설정<br/>save_user_preference / inspect_status"| MEM_TOOL["Session & Memory Bank 직접 처리"]

  HANDOFF -->|"VIP/휴면/유입경로/장바구니"| SUB1["Sub-Agent 1<br/>customer_marketing_subagent"]
  HANDOFF -->|"마진율/환불률/카테고리/브랜드"| SUB2["Sub-Agent 2<br/>product_profitability_subagent"]
  HANDOFF -->|"물류센터/배송시간/미판매재고"| SUB3["Sub-Agent 3<br/>supply_chain_logistics_subagent"]

  SUB1 <-->|"후속 Turn Domain 전환 시<br/>Peer-to-Peer Transfer"| SUB2
  SUB2 <-->|"후속 Turn Domain 전환 시<br/>Peer-to-Peer Transfer"| SUB3

  SUB1 -->|"ask_customer_marketing_caa()"| CAA1[("BQ CAA #1<br/>thelook_customer_marketing_ca")]
  SUB2 -->|"ask_product_profitability_caa()"| CAA2[("BQ CAA #2<br/>thelook_product_profitability_ca")]
  SUB3 -->|"ask_supply_chain_logistics_caa()"| CAA3[("BQ CAA #3<br/>thelook_supply_chain_ca")]

  PARALLEL --> CAA1
  PARALLEL --> CAA2
  PARALLEL --> CAA3
```

### 2.1 [Path A] 단일 Domain 질문 — ADK Built-in `transfer_to_agent` 위임 Mechanism
1. **Prompt 자동 주입 (`_AgentTransferLlmRequestProcessor`)**:
   - `root_agent`에 `sub_agents=[customer_marketing_subagent, product_profitability_subagent, supply_chain_logistics_subagent]`를 선언하면, ADK Runtime이 매 Turn LLM 호출 직전에 각 Sub-Agent의 `name`과 `description`을 System Prompt에 자동 주입합니다.
2. **JSON Schema `enum` 제약 (`TransferToAgentTool`)**:
   - ADK는 `transfer_to_agent(agent_name: str)` Tool을 생성할 때 Parameter Schema에 `enum: ["customer_marketing_subagent", "product_profitability_subagent", "supply_chain_logistics_subagent"]` 제약을 강제합니다. 따라서 LLM이 존재하지 않는 Agent 이름을 Hallucination으로 생성하는 것이 불가능합니다.
3. **동일 Turn 내 즉시 제어권 Switching (`EventActions.transfer_to_agent`)**:
   - Root Agent가 `transfer_to_agent(agent_name="customer_marketing_subagent")`를 호출하면 `tool_context.actions.transfer_to_agent` Flag가 설정됩니다.
   - ADK `Runner`가 이 Flag를 가로채어 **사용자 추가 입력 없이 동일 Turn 안에서 즉시 `customer_marketing_subagent`를 실행**합니다.
4. **전용 Tool을 통한 1:1 CAA Binding**:
   - 실행된 `customer_marketing_subagent`는 오직 `ask_customer_marketing_caa` Tool만 보유하고 있으므로, 무조건 `thelook_customer_marketing_ca` Agent로만 Query를 전송합니다.

### 2.2 [Path B] Multi-Turn 후속 질문의 Domain 전환 — Peer-to-Peer & Parent Transfer
- Turn 1에서 `customer_marketing_subagent`가 응답을 마치면, Session의 현재 Active Agent는 `customer_marketing_subagent`가 됩니다.
- Turn 2에서 사용자가 **"그럼 물류센터별 평균 배송 소요 시간은 어때?"**(Domain 3 질문)라고 물으면 어떻게 될까요?
- ADK의 `_get_transfer_targets(agent)` Function은 현재 Active Sub-Agent에게 **(1) Parent Agent(`thelook_enterprise_root_router`)**와 **(2) Peer Sub-Agents(`product_profitability_subagent`, `supply_chain_logistics_subagent`)**를 모두 Transfer 대상으로 열어 줍니다.
- 따라서 `customer_marketing_subagent`는 Root를 거치지 않고 곧바로 `transfer_to_agent(agent_name="supply_chain_logistics_subagent")`를 호출하여 **수평 이관(Peer Transfer)**을 수행합니다.

### 2.3 [Path C] 복합 Domain 질문 — `run_cross_domain_caa_analysis` 병렬 Fan-out
- 사용자가 한 문장 안에 2~3개 Domain의 지표를 동시에 요구할 때(예: *"유입 경로별 VIP 사용자 수, 상품 카테고리별 평균 마진율, 물류센터별 평균 배송 소요 시간을 한 번에 종합 Report로 비교해줘"*), 단일 Sub-Agent로 제어권을 넘기면 다른 Domain의 Table을 조회할 수 없습니다.
- 이때 Root Agent는 제어권을 넘기지 않고 직접 `run_cross_domain_caa_analysis(...)` Tool을 호출합니다.
- 이 Tool은 질문을 Domain별 Sub-Query로 분해(Query Decomposition)한 뒤, Python `ThreadPoolExecutor`를 통해 **3개 Domain CAA Agent의 `:chat` API를 동시에 병렬 호출**하여 대기 시간을 약 60% 단축하고 하나의 종합 Report로 합성합니다.

---

## 3. 왜 "ADK `Session Object` + `Memory Object` Architecture Pattern"이 필요한가?

### 3.1 무이력 단발 호출(One-Shot Stateless) 및 관리형 `ConversationReference`의 한계점
1. **무이력 단발 호출 시의 Turn 간 Context 단절 (One-Shot Stateless Amnesia)**:
   - 공식 API의 Stateless Mode(`DataAgentContext` / `InlineContext`) 자체는 Application이 `messages` 배열에 이전 이력을 담아 전송하면 Multi-Turn 대화가 가능합니다. 그러나 ADK 기본 내장 `DataAgentToolset`의 `ask_data_agent`는 내부적으로 `messages`에 **현재 질문 1개만 담아 단발성으로 호출**하도록 구현되어 있어, 별도의 이력 체이닝 없이는 Turn 2에서 *"그 중 환불률이 가장 높은 브랜드는?"*이라고 물었을 때 이전 Turn의 SQL 조건을 기억하지 못합니다.
   - 반면 관리형 Stateful Mode(`ConversationReference`)는 단일 Agent 대화에서는 정확도 측면에서 공식 권장되지만, **`1 Conversation = 1 Data Agent` 고정 귀속 제약**으로 인해 3개 Domain CAA를 오가는 Multi-Agent 환경에서는 도메인 전환 즉시 문맥이 단절됩니다(보관 주기는 마지막 활동 후 180일 비활성 시 자동 삭제 → 30일 복구 불가 Soft Delete → 63일 내 영구 파기이며, CMEK는 `global`이 아닌 Regional/Multi-Regional Location에서만 지원).
2. **Session 종료 후 사용자 Context 초기화 (Cross-Session Amnesia)**:
   - 현업 사용자(예: 여성복 MD 팀장)가 매번 새 채팅창(`+ New Session`)을 열 때마다 *"나는 여성복(Women) 부서 담당이고 마진율과 환불률을 중점 관리해"*라고 반복해서 설명해야 합니다.
3. **Tool 실행 결과의 휘발 및 무분별한 누적 비용**:
   - 이전 Session에서 도출했던 중요한 분석 결론이 다음 날 회의 시점에는 사라지거나, 반대로 단일 Session 내에 수십 행의 원본 JSON과 중간 추론(`THOUGHT`)이 그대로 쌓여 입력 Token 비용이 급증합니다.

### 3.2 본 Architecture에서 강화된 2대 핵심 축: `Session Object` & `Memory Object`

```mermaid
flowchart LR
  subgraph SessionObj["축 1: ADK Session Object (ctx.session & 4-Scope State)"]
    S1["1. temp:* (Invocation Scope)<br/>temp:last_caa_sql, temp:last_caa_rows<br/>→ 동일 Turn 내 전달 후 종료 시 자동 소멸 (영속 Session DB 오염 방지)"]
    S2["2. session (Session Scope)<br/>domain_query_history, domain_ca_multiturn_messages[-6:]<br/>→ 동일 Domain 3-Turn CAA History Chaining & 이종 Domain 완결형 질의 재작성"]
    S3["3. user:* (User Persistent Scope)<br/>user:profile, user:preferred_kpis, user:pinned_insights<br/>→ 새 Session(+ New Session)을 열어도 사용자 직무/관심부서/KPI 자동 유지"]
    S4["4. app:* (Global App Scope)<br/>app:total_caa_queries_executed<br/>→ Application 전체 누적 CAA Query 실행 통계 추적"]
  end

  subgraph MemoryObj["축 2: ADK Memory Object (ctx.memory_service + Disk Backup)"]
    M1["before_agent_callback<br/>(_initialize_session_and_rehydrate_memory)<br/>→ 새 Session 시작 시 .adk/long_term_memory_bank.json에서 과거 Memory 자동 복원"]
    M2["after_agent_callback<br/>(_save_session_to_long_term_memory)<br/>→ 매 Turn 종료 시 await ctx.add_session_to_memory() 호출 및 Disk 증분 저장"]
    M3["PreloadMemoryTool & LoadMemoryTool<br/>→ 매 Turn 질문과 연관된 과거 Session의 SQL·Insight를 <PAST_CONVERSATIONS>로 자동 주입"]
  end

  SessionObj <==>|"상호 보완 연동"| MemoryObj
```

#### 강화 Point 상세 비교표

| 구분 | 미적용 시 (기본 단발 호출 또는 미정제 구성) | **적용 후 (`bq_caa_3domain_multi_agent`)** | 구현 Code 위치 (`agent.py`) |
| :--- | :--- | :--- | :--- |
| **단일 Turn 임시 Data 관리 및 Prompt Diet** | 조회된 대량 Row와 `THOUGHT` 로그가 Tool 반환값 및 영속 Session DB에 그대로 남아 Token 낭비 유발 | 원본 배열은 **`temp:last_caa_rows` / `temp:last_caa_sql`**에 저장해 Turn 종료 시 자동 소멸(Session DB 오염 방지)시키고, Tool 반환값은 **20행 Markdown 요약 + `THOUGHT`/`PROGRESS` 제거**로 경량화하여 다음 Turn LLM Prompt 오염 차단 | `_record_caa_result_into_session_state`, `_query_domain_caa_agent` |
| **하위 CAA Multi-Turn Chaining 및 이종 Domain 문맥 계승** | 매 질문을 독립된 단발성 질문으로 CAA에 전달하거나 도메인 전환 시 문맥 단절 | 동일 Domain은 **`domain_ca_multiturn_messages[-6:]`**(최근 3 Turn = 6개 Message)를 CAA `:chat` API(`DataAgentContext`, 필요 권한: `dataAgentUser`)의 `messages` 배열에 자동 Chaining하고, 이종 Domain 간에는 ADK Sub-Agent가 공유 **`domain_query_history`**를 참조해 완결형 질의(Standalone Query)로 재작성하여 호출 | `_query_domain_caa_agent` |
| **Session 간 사용자 Profile/선호 KPI 유지** | 새 Session 생성 시 사용자 역할·담당 부서 초기화 | **`user:profile`**, **`user:preferred_kpis`** Scope를 통해 새 Session을 열어도 `"Women 부서 담당 MD 본부장"` 설정이 Prompt(`{user:profile?}`)에 자동 반영 | `save_user_preference_and_memory` |
| **Long-Term Memory 자동 수집 및 검색** | 이전 Session의 분석 결과 조회 불가 | **`after_agent_callback`(`add_session_to_memory`)** + **`preload_memory` / `load_memory`** + **`.adk/long_term_memory_bank.json`** 영속화로 Server 재시작 후에도 과거 분석 Insight 즉시 검색 | `_initialize_session_and_rehydrate_memory`, `_save_session_to_long_term_memory` |
