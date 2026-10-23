# BigQuery Conversational Analytics (CAA) & Google ADK Multi-Agent Hands-on Lab
**(Domain-Scoped 3-SubAgent Routing + ADK `Session` & `Memory` 기반 Token 최적화 Architecture)**

[![Google Cloud](https://img.shields.io/badge/Google_Cloud-BigQuery_CAA-4285F4?logo=googlecloud)](https://cloud.google.com/bigquery)
[![Google ADK](https://img.shields.io/badge/Google_ADK-v2.7+-34A853?logo=google)](https://adk.dev/)
[![Terraform](https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform)](./terraform/)

본 Repository는 사용자의 Google Cloud 환경에서 **`bigquery-public-data.thelook_ecommerce` 기반의 신규 Dataset(`<PROJECT_ID>.thelook_ecommerce_agent`, 기본 Region: `US`)을 자동으로 생성하고 Demo Scenario용 Golden Data를 증강**한 뒤, **Root Agent + 3대 Domain BigQuery CAA Sub-Agents Routing**과 **ADK `Session Object`(4-Scope State) + `Memory Object`(Long-Term Memory) Architecture**를 단계별로 구축하고 검증할 수 있도록 구성한 Qwiklabs 스타일 Hands-on Lab입니다 (`[확인됨 / Verified: bq_caa_3domain_multi_agent/agent.py]`).

> [!IMPORTANT]
> **공식 Integration Pattern 및 State Management 설계 배경 (`[확인됨 / Verified: Google Cloud Official Docs]`)**
> Google Cloud 공식 문서인 [Integration patterns for data agents](https://cloud.google.com/gemini/docs/conversational-analytics-api/integration-patterns)와 [State management for data agents](https://cloud.google.com/gemini/docs/conversational-analytics-api/state-management)에서는 BQ CAA 연동 방식을 크게 **Direct API, ADK, MCP, A2A의 4대 Integration Approach(총 7개 세부 Pattern)**와 **3가지 API Context Mode(`ConversationReference`, `DataAgentContext`, `InlineContext`)**로 정의하고 있습니다. 본 Repository는 그중 Enterprise Multi-Agent 환경에서 Governance(Business Glossary 및 Verified Queries)가 보장되는 **핵심 Pattern들(ADK `DataAgentToolset`, ADK `Custom Streaming Sub-Agent`, `Direct API Orchestrator`, `A2A`/`MCP`)**을 추려 비교하고, 실제 대규모 운영 시 발생하는 Input Token 비용 문제를 해결하기 위해 **ADK `Session` 및 `Memory` 기반의 경량 최적화 Best Practice**를 결합한 아키텍처 구현체입니다.

---

## Documentation Index

본 Repository의 상세 기술 해설서와 실습 가이드는 `docs/` Directory 아래 세 개의 문서로 구성되어 있습니다.

| 문서 명칭 및 경로 | 대상 독자 및 주요 수록 내용 |
| :--- | :--- |
| **[1. Qwiklabs Step-by-Step Hands-on Lab Guide (`docs/QWIKLABS_HANDSON_LAB_GUIDE_KO.md`)](docs/QWIKLABS_HANDSON_LAB_GUIDE_KO.md)** | Overview 및 사전 준비부터 Task 1 ~ Task 5까지의 단계별 실행 Command, 설계 배경, 그리고 `Check My Progress` 자가 진단 Script 안내 |
| **[2. Architecture Deep Dive Technical Whitepaper (`docs/ARCHITECTURE_DEEP_DIVE_KO.md`)](docs/ARCHITECTURE_DEEP_DIVE_KO.md)** | 공식 4대 Integration Approach(7개 세부 Pattern) 및 3대 API Context Mode 비교, Root Agent → 3 BQ CAA Sub-Agents Routing Logic(`transfer_to_agent`, Peer-to-Peer 전환, 병렬 Fan-out), 4-Scope `Session.state` 및 `MemoryService` 기반 Token Diet 설계 원리 |
| **[3. Code Walkthrough & Session/Memory API Reference (`docs/CODE_WALKTHROUGH_ROOT_AGENT_AND_SESSION_KO.md`)](docs/CODE_WALKTHROUGH_ROOT_AGENT_AND_SESSION_KO.md)** | Repository 내 Python File별 역할 구분, [`bq_caa_3domain_multi_agent/agent.py`](bq_caa_3domain_multi_agent/agent.py) Line별 Code Map(`L1–L1132`), ADK 표준 Library(`CallbackContext`, `ToolContext`, `Event`, `preload_memory`, `load_memory`) 및 5대 내부 Function 상세 분석 |

---

## System Architecture & Key Value Propositions

복잡한 Enterprise Data Warehouse 환경에서 단일 거대 CAA Agent를 사용할 때 발생하는 Input Token 폭증과 유사 Column 오조인 문제를 방지하기 위해, 본 Architecture는 데이터 준비(Data Prep), Domain 분리형 CAA Layer, 그리고 ADK Orchestration Layer의 3계층으로 구성됩니다.

```mermaid
flowchart TD
  classDef prepNode fill:#FFFFFF,stroke:#4285F4,stroke-width:2px,color:#202124
  classDef caaNode fill:#FFFFFF,stroke:#EA4335,stroke-width:2px,color:#202124
  classDef adkNode fill:#FFFFFF,stroke:#34A853,stroke-width:2px,color:#202124
  classDef stateNode fill:#F8F9FA,stroke:#FBBC04,stroke-width:2px,color:#202124

  subgraph DataPrep["1. Data Prep Layer (Terraform + SQL)"]
    PUB["bigquery-public-data.thelook_ecommerce<br/>(US Multi-Region)"]:::prepNode -->|"01_clone_public_thelook.sql<br/>(15s CTAS Fast Clone)"| DS["<USER_PROJECT>.thelook_ecommerce_agent<br/>(7 Core Tables + Seeded Golden Data)"]:::prepNode
    SEED["02_seed_demo_scenarios.sql<br/>(VIP / High-Margin Return / DC Delay Seed)"]:::prepNode --> DS
  end

  subgraph CAALayer["2. Domain-Scoped BigQuery CAA Layer (3 Pre-configured Data Agents)"]
    CAA1["BQ CAA #1: thelook_customer_marketing_ca<br/>Scoped Tables (4): users, events, orders, order_items"]:::caaNode
    CAA2["BQ CAA #2: thelook_product_profitability_ca<br/>Scoped Tables (3): products, order_items, orders"]:::caaNode
    CAA3["BQ CAA #3: thelook_supply_chain_ca<br/>Scoped Tables (5): distribution_centers, inventory_items, ..."]:::caaNode
    DS --> CAA1
    DS --> CAA2
    DS --> CAA3
  end

  subgraph ADKLayer["3. Google ADK Orchestration Layer (bq_caa_3domain_multi_agent)"]
    ROOT["Root Router Agent (thelook_enterprise_root_router)<br/>+ 3 Domain Sub-Agents"]:::adkNode
    SM["ADK Session Object (4-Scope State: temp: / session / user: / app:)<br/>+ Memory Object (Long-Term Memory Bank)"]:::stateNode
    ROOT <--> SM
    ROOT -->|"transfer_to_agent / Parallel Fan-out"| CAA1
    ROOT -->|"transfer_to_agent / Parallel Fan-out"| CAA2
    ROOT -->|"transfer_to_agent / Parallel Fan-out"| CAA3
  end
```

### 핵심 설계 가치 비교 (Key Value Propositions)

| 핵심 과제 | 기존 단일 Agent 또는 기본 단발성 호출의 한계 | 본 Repository Architecture의 해결 방식 (`bq_caa_3domain_multi_agent`) |
| :--- | :--- | :--- |
| **1. Domain Routing 및 Token/정확도 최적화** | 모든 Table과 Business Glossary를 1개 CAA Agent에 연결하거나 매번 `list`/`get_data_agent_info`를 호출하여 Input Token 급증 및 유사 Column(`created_at`) 오조인 발생 | **Root Agent + 3 Domain-Scoped CAA Sub-Agents**: Domain별 필수 Table(4/3/5개)과 전용 Business Glossary만 분리 연결하고, 정적 `agent_id` Tool Binding(Metadata 탐색 Overhead 제거)과 `transfer_to_agent` / `ThreadPoolExecutor` 병렬 Fan-out으로 처리 |
| **2. Multi-Turn 대화 Context 유지 및 Token 상한 관리 (`Session Object`)** | ADK 기본 `ask_data_agent`는 매 요청에 현재 질의 1개만 전달(One-Shot Stateless)하여 후속 질의에서 직전 SQL 조건을 상실함 (반면 관리형 `ConversationReference`는 `1 Conversation = 1 Agent` 제약으로 Domain 전환 시 문맥 단절) | **Stateless API(`DataAgentContext`) + ADK 4-Scope `Session.state` (`temp:`, `session`, `user:`, `app:`)**: 동일 Domain은 `domain_ca_multiturn_messages[-6:]`(최근 3 Turn = 6개 Message)를 CAA `:chat` API의 `messages` 필드에 자동 Chaining하고, 이종 Domain 간에는 `domain_query_history` 기반 완결형 질의 재작성(Standalone Query Rewriting) 및 Tool 반환값 경량화(20행 요약 + `THOUGHT`/`PROGRESS` 제거) 적용 |
| **3. Cross-Session Long-Term Memory (`Memory Object`)** | 새 채팅(`+ New Session`) 생성 시 사용자의 담당 부서·중점 KPI·이전 분석 Insight 초기화 | **`after_agent_callback`(`add_session_to_memory`) + `preload_memory` / `load_memory` + `.adk/long_term_memory_bank.json`**: 새 Session을 열거나 Server를 재시작해도 사용자 Profile(`user:profile`)과 과거 분석 결론을 즉시 복원 |

---

## Repository Directory Structure

```text
.
├── README.md                                     # Repository 개요 및 Quickstart Guide
├── docs/
│   ├── QWIKLABS_HANDSON_LAB_GUIDE_KO.md            # Qwiklabs 형식 단계별 Hands-on Lab Guide (Task 1~5)
│   ├── ARCHITECTURE_DEEP_DIVE_KO.md                # Routing Logic 및 Session/Memory Architecture 심층 해설서
│   └── CODE_WALKTHROUGH_ROOT_AGENT_AND_SESSION_KO.md # Root Agent 구성 .py Code Map & Session/Memory API Reference
├── scripts/
│   ├── 00_configure_customer_env.sh              # 사용자 정보(PROJECT_ID, DATASET_ID, REGION) 대화형 설정 Wizard
│   ├── 01_prepare_bigquery_data.py               # Public Data 복제(15초 CTAS) + 3대 Domain Demo Data Seeding
│   ├── 02_provision_bq_caa_agents.py             # 6개 BigQuery CAA Agent 자동 Provisioning
│   └── 03_verify_lab_progress.py                 # Qwiklabs 'Check My Progress' 스타일 단계별 완료 검증기
├── terraform/
│   ├── versions.tf                               # Terraform & Google Provider Version 정의
│   ├── variables.tf                              # project_id, dataset_id(thelook_ecommerce_agent), bq_location(US)
│   ├── main.tf                                   # GCP API 활성화 + BigQuery Dataset + Data/CAA Provisioning
│   ├── outputs.tf                                # Provisioning 결과 출력
│   └── terraform.tfvars.example                  # 사용자 Variable 입력 예시 File
├── sql/
│   ├── 01_clone_public_thelook.sql               # bigquery-public-data.thelook_ecommerce 7개 Table 복제 SQL
│   └── 02_seed_demo_scenarios.sql                # VIP 사용자 / 고마진 반품 Anomaly / 물류센터 배송지연 Seed SQL
├── bq_caa_3domain_multi_agent/                   # [Main Lab] Root Router + 3 Domain CAA Sub-Agents + Session/Memory
├── bq_caa_toolset_agent/                         # [Comparison] Single CAA Agent (Baseline vs. Governed 비교용)
├── bq_caa_streaming_agent/                       # [Streaming] Custom Streaming Sub-Agent + State Handoff
├── setup_mac_adk.sh                              # 원클릭 Python .venv + SSL 인증서 Bundle + ADK Web UI Launcher
├── run_adk_web.sh                                # ADK Web UI (http://127.0.0.1:8000/dev-ui/) 빠른 재실행 Script
└── pyproject.toml                                # Python Package 의존성 정의 (google-adk, google-genai, truststore 등)
```

---

## 5분 Quickstart (실습 환경 실행 순서)

### Step 1. 사용자 GCP Project 정보 설정 (`thelook_ecommerce_agent`, Region `US` 기본값)
```bash
chmod +x scripts/00_configure_customer_env.sh setup_mac_adk.sh run_adk_web.sh
./scripts/00_configure_customer_env.sh
source customer_config.env
```

### Step 2. BigQuery Dataset 복제 + Scenario Data 추가 + CAA Agent 생성
- **방법 A (Python Script 실행 — 약 40초 완료)**:
  ```bash
  python3 scripts/01_prepare_bigquery_data.py
  python3 provision_bq_caa_demo.py
  ```
- **방법 B (Terraform 일괄 실행)**:
  ```bash
  cd terraform && terraform init && terraform apply -auto-approve && cd ..
  ```

### Step 3. 실습 환경 자가 검증 (`Check My Progress`)
```bash
python3 scripts/03_verify_lab_progress.py --all
```

### Step 4. Google ADK Web UI 실행 및 실습 진행
```bash
./setup_mac_adk.sh "$GOOGLE_CLOUD_PROJECT" "$BQ_DATASET_ID"
```
Browser에서 **[http://127.0.0.1:8000/dev-ui/](http://127.0.0.1:8000/dev-ui/)** 접속 후 상세 Prompt Scenario는 **[`docs/QWIKLABS_HANDSON_LAB_GUIDE_KO.md`](docs/QWIKLABS_HANDSON_LAB_GUIDE_KO.md)**의 **Task 4 & Task 5**를 따라 진행합니다.
