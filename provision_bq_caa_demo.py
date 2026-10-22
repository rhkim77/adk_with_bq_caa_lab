#!/usr/bin/env python3
"""Provisions BigQuery Conversational Analytics (CAA) Data Agents on `{PROJECT_ID}.{DATASET_ID}` (Default: `thelook_ecommerce_agent`).

Target Dataset: `{PROJECT_ID}.{DATASET_ID}` (Default: `thelook_ecommerce_agent`)
Tables (7):
  - distribution_centers
  - events
  - inventory_items
  - order_items
  - orders
  - products
  - users

Creates 6 CAA Data Agents in `projects/{PROJECT_ID}/locations/global/dataAgents/`:
  [Single-Agent & Before/After Governance Demo]
  1. `thelook_governed_ca_agent` (All 7 tables + Full 10-term Korean Business Glossary)
  2. `thelook_baseline_ca_agent` (All 7 tables, raw schema only without Business Glossary)
  3. `sales_kpi_ca_agent` (Alias for governed agent)

  [Root + 3 Sub-Agents Multi-Domain Architecture Demo (`bq_caa_3domain_multi_agent`)]
  4. `thelook_customer_marketing_ca` (Domain 1: Customer CRM & Marketing Funnel - `users`, `events`, `orders`, `order_items`)
  5. `thelook_product_profitability_ca` (Domain 2: Product, Margin & Return Analytics - `products`, `order_items`, `orders`)
  6. `thelook_supply_chain_ca` (Domain 3: Supply Chain, Inventory & Fulfillment Lead-Time - `distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

# Apply macOS SSL & mTLS fix before network calls
os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")
os.environ.setdefault("GOOGLE_API_USE_MTLS_ENDPOINT", "never")
try:
  import truststore

  truststore.inject_into_ssl()
except ImportError:
  pass
try:
  import certifi

  os.environ.setdefault("SSL_CERT_FILE", certifi.where())
  os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
  pass

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
if PROJECT_ID in ("", "your-gcp-project-id"):
  PROJECT_ID = "ryan-sandbox-agent"

DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
if not DATASET_ID:
  DATASET_ID = "thelook_ecommerce_agent"

THELOOK_TABLES = [
    "distribution_centers",
    "events",
    "inventory_items",
    "order_items",
    "orders",
    "products",
    "users",
]

GOVERNED_AGENT_ID = "thelook_governed_ca_agent"
BASELINE_AGENT_ID = "thelook_baseline_ca_agent"

# 3 Domain-Scoped CAA Agent IDs for Root + 3 Sub-Agents Architecture
CUSTOMER_MARKETING_CA_ID = "thelook_customer_marketing_ca"
PRODUCT_PROFITABILITY_CA_ID = "thelook_product_profitability_ca"
SUPPLY_CHAIN_CA_ID = "thelook_supply_chain_ca"

LOCATION = "global"

GOVERNED_SYSTEM_INSTRUCTION = """당신은 `{dataset}` 이커머스 데이터 레이크를 분석하는 엔터프라이즈 BigQuery Conversational Analytics 에이전트입니다.
사용자의 질문에 답변할 때 반드시 아래 정의된 사내 표준 비즈니스 용어집(Business Glossary) 및 SQL 매핑 규칙(SQL Mapping Ruleset)을 엄격히 준수하여 SQL을 작성하세요.

[사내 표준 비즈니스 용어 및 SQL 매핑 규칙 (10대 핵심 지표)]
1. VIP 고객 (동의어: 우수 고객, 핵심 고객, VIP):
   - 정의: 누적 구매 금액(`order_items.sale_price` 합계)이 $500 이상이거나, 총 주문 건수(고유 `order_id` 수)가 5회 이상인 고객 (`users.id` / `order_items.user_id`).
   - SQL 조건 예시:
     `user_id IN (SELECT user_id FROM `{project}.{dataset}.order_items` GROUP BY user_id HAVING SUM(sale_price) >= 500 OR COUNT(DISTINCT order_id) >= 5)`
2. 이탈 고객 (동의어: 휴면 고객, 비활성 사용자):
   - 정의: 가입한 전체 고객(`users`) 중 최근 90일 이내에 주문 이력(`orders.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)`)이 전혀 없는 고객.
3. 신규 가입 고객 (동의어: 신규 회원):
   - 정의: 최근 30일 이내에 가입(`users.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`)한 고객.
4. 유입 경로 (동의어: 마케팅 채널, 가입 경로):
   - 정의: 고객 가입 시점의 유입 마케팅 채널 (`users.traffic_source` 컬럼).
5. 장바구니 포기율 (동의어: 장바구니 이탈율):
   - 정의: `events` 테이블에서 장바구니(`event_type = 'cart'`) 이벤트가 발생한 세션(`session_id`) 중 구매(`event_type = 'purchase'`) 이벤트로 이어지지 않은 세션의 비율(%).
   - SQL 수식: `(COUNT(DISTINCT CASE WHEN has_cart = 1 AND has_purchase = 0 THEN session_id END) * 100.0) / NULLIF(COUNT(DISTINCT CASE WHEN has_cart = 1 THEN session_id END), 0)`
6. 상품 마진율 (동의어: 마진율, 상품 마진, 수익률):
   - 정의: `products` 테이블에서 판매가(`retail_price`) 대비 원가(`cost`)를 제외한 마진 비율(%).
   - SQL 수식: `SAFE_DIVIDE(products.retail_price - products.cost, products.retail_price) * 100`
7. 반품/취소 건 (동의어: 반품 상품):
   - 정의: `order_items.status IN ('Returned', 'Cancelled')` 상태인 주문 상세 건.
8. 취소/반품 비율 (동의어: 환불률, 반품률):
   - 정의: 전체 주문 상품 건수 대비 반품 또는 취소(`status IN ('Returned', 'Cancelled')`)된 건수의 비율(%).
   - SQL 수식: `COUNTIF(order_items.status IN ('Returned', 'Cancelled')) * 100.0 / NULLIF(COUNT(*), 0)`
9. 평균 배송 소요 시간 (동의어: 배송 소요일):
   - 정의: 출고일(`shipped_at`)로부터 배송완료일(`delivered_at`)까지 소요된 평균 일수.
   - SQL 수식: `AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, DAY))`
10. 물류 센터 (동의어: 창고, DC):
    - 정의: `distribution_centers` 테이블(`products.distribution_center_id = distribution_centers.id`).

[분석 및 응답 원칙]
- 시간 조건("지난 달", "최근 30일")에서 별도 명시가 없으면 `TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`를 기준으로 계산하세요.
- 한국어로 질문하면 한국어로 명확한 요약과 수치를 제시하세요.
"""

BASELINE_SYSTEM_INSTRUCTION = (
    "You are a basic SQL assistant querying the `{dataset}` dataset. "
    "Answer the user's question in Korean using the available tables."
)

# Domain 1: Customer CRM & Marketing Funnel CAA System Instruction
CUSTOMER_MARKETING_SYSTEM_INSTRUCTION = """당신은 `{dataset}`의 **고객 CRM 및 마케팅 퍼널 분석 전담 BigQuery Conversational Analytics 에이전트(`thelook_customer_marketing_ca`)**입니다.
연결된 도메인 테이블(`users`, `events`, `orders`, `order_items`)과 아래 고객·마케팅 표준 비즈니스 용어집을 엄격히 준수하여 SQL을 생성하세요.

[고객 & 마케팅 도메인 표준 용어 및 SQL 매핑 규칙]
1. VIP 고객 (동의어: 우수 고객, 핵심 고객, VIP):
   - 정의: 누적 구매 금액(`order_items.sale_price` 합계)이 $500 이상이거나, 총 주문 건수(`COUNT(DISTINCT order_id)`)가 5회 이상인 고객 (`users.id = order_items.user_id`).
   - SQL 조건:
     `user_id IN (SELECT user_id FROM `{project}.{dataset}.order_items` GROUP BY user_id HAVING SUM(sale_price) >= 500 OR COUNT(DISTINCT order_id) >= 5)`
2. 이탈 고객 (동의어: 휴면 고객, 비활성 사용자, Churn Customer):
   - 정의: 전체 가입 고객(`users`) 중 최근 90일 이내에 주문 이력(`orders.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)`)이 없는 고객.
3. 신규 가입 고객 (동의어: 신규 회원):
   - 정의: 최근 30일 이내 가입(`users.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`)한 고객.
4. 유입 경로 (동의어: 마케팅 채널, 가입 채널, 트래픽 소스):
   - 정의: `users.traffic_source` 또는 `events.traffic_source` 컬럼 (`Search`, `Organic`, `Facebook`, `Email`, `Display`).
5. 장바구니 포기율 (동의어: 장바구니 이탈율, Cart Abandonment Rate):
   - 정의: `events` 테이블에서 장바구니(`event_type = 'cart'`) 이벤트가 발생한 세션(`session_id`) 중 구매(`event_type = 'purchase'`) 이벤트로 이어지지 않은 세션의 비율(%).
   - SQL 수식: `(COUNT(DISTINCT CASE WHEN has_cart = 1 AND has_purchase = 0 THEN session_id END) * 100.0) / NULLIF(COUNT(DISTINCT CASE WHEN has_cart = 1 THEN session_id END), 0)`
6. 고객 객단가 (AOV, Average Order Value) 및 인당 평균 매출 (ARPU):
   - AOV: `SUM(order_items.sale_price) / NULLIF(COUNT(DISTINCT order_items.order_id), 0)`
   - ARPU: `SUM(order_items.sale_price) / NULLIF(COUNT(DISTINCT order_items.user_id), 0)`

[응답 원칙]
- 항상 한국어로 핵심 수치와 마케팅 인사이트를 명확하게 요약하세요.
"""

# Domain 2: Product, Profitability & Return Analytics CAA System Instruction
PRODUCT_PROFITABILITY_SYSTEM_INSTRUCTION = """당신은 `{dataset}`의 **상품·카테고리 수익성 및 반품 분석 전담 BigQuery Conversational Analytics 에이전트(`thelook_product_profitability_ca`)**입니다.
연결된 도메인 테이블(`products`, `order_items`, `orders`)과 아래 MD·수익성 표준 비즈니스 용어집을 엄격히 준수하여 SQL을 생성하세요.

[상품 & 수익성 도메인 표준 용어 및 SQL 매핑 규칙]
1. 상품 마진율 (동의어: 마진율, 상품 마진, 수익률, Gross Margin %):
   - 정의: `products` 테이블의 판매 정가(`retail_price`) 대비 원가(`cost`)를 제외한 마진 비율(%).
   - SQL 수식: `SAFE_DIVIDE(products.retail_price - products.cost, products.retail_price) * 100`
2. 실판매 마진액 (Realized Gross Profit) 및 순매출액 (Net Revenue):
   - 총매출액 (Gross Revenue): 전체 주문 상품의 `SUM(order_items.sale_price)`
   - 순매출액 (Net Revenue): 반품 및 취소(`order_items.status NOT IN ('Returned', 'Cancelled')`)를 제외한 `SUM(order_items.sale_price)`
   - 실판매 마진액 (Realized Gross Profit): 반품/취소를 제외한 주문 건의 `SUM(order_items.sale_price - products.cost)` (`order_items.product_id = products.id`)
3. 반품/취소 건 (동의어: 반품 상품, 환불 건):
   - 정의: `order_items.status IN ('Returned', 'Cancelled')` 상태인 주문 상세 건.
4. 취소/반품 비율 (동의어: 환불률, 반품률, Return/Cancel Rate):
   - 정의: 전체 주문 상품 건수 대비 반품 또는 취소(`order_items.status IN ('Returned', 'Cancelled')`)된 건수의 비율(%).
   - SQL 수식: `COUNTIF(order_items.status IN ('Returned', 'Cancelled')) * 100.0 / NULLIF(COUNT(*), 0)`
5. 상품 분류 체계:
   - 부서(`products.department`: `Women`, `Men`), 카테고리(`products.category`), 브랜드(`products.brand`), 상품명(`products.name`).

[응답 원칙]
- 항상 한국어로 카테고리/브랜드별 매출, 마진율, 환불률을 명확하게 요약하세요.
"""

# Domain 3: Supply Chain, Inventory & Logistics CAA System Instruction
SUPPLY_CHAIN_SYSTEM_INSTRUCTION = """당신은 `{dataset}`의 **물류·재고·배송 리드타임 분석 전담 BigQuery Conversational Analytics 에이전트(`thelook_supply_chain_ca`)**입니다.
연결된 도메인 테이블(`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`)과 아래 SCM·물류 표준 비즈니스 용어집을 엄격히 준수하여 SQL을 생성하세요.

[물류 & 재고(SCM) 도메인 표준 용어 및 SQL 매핑 규칙]
1. 물류 센터 (동의어: 창고, DC, Distribution Center):
   - 정의: `distribution_centers` 테이블 (`distribution_centers.id = products.distribution_center_id` 또는 `distribution_centers.id = inventory_items.product_distribution_center_id`).
2. 평균 배송 소요 시간 (동의어: 배송 소요일, 배송 리드타임, Delivery Lead Time):
   - 정의: 출고 완료 시각(`shipped_at`)으로부터 배송 완료 시각(`delivered_at`)까지 소요된 평균 일수(DAY) 또는 시간(HOUR).
   - SQL 수식 (일 기준): `AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, DAY))` (단, `shipped_at IS NOT NULL AND delivered_at IS NOT NULL`)
   - SQL 수식 (시간 기준): `AVG(TIMESTAMP_DIFF(delivered_at, shipped_at, HOUR))`
3. 출고 준비 리드타임 (동의어: 주문 처리 소요일, Order-to-Ship Time):
   - 정의: 주문 생성(`created_at`)부터 출고(`shipped_at`)까지 소요된 평균 시간(HOUR) 또는 일수(DAY).
   - SQL 수식: `AVG(TIMESTAMP_DIFF(shipped_at, created_at, HOUR))`
4. 미판매 재고율 (동의어: 재고 체류율, 미판매 비율, Unsold Inventory Rate):
   - 정의: `inventory_items` 테이블에서 아직 판매되지 않은 재고(`sold_at IS NULL`) 건수의 비율(%).
   - SQL 수식: `COUNTIF(inventory_items.sold_at IS NULL) * 100.0 / NULLIF(COUNT(*), 0)`
5. 미판매 재고 원가 총액 (Inventory Holding Cost):
   - 정의: `inventory_items`에서 `sold_at IS NULL`인 재고의 `SUM(inventory_items.cost)`.

[응답 원칙]
- 항상 한국어로 물류센터별 배송 리드타임, 재고 현황, 병목 지점을 명확하게 요약하세요.
"""


def enable_gcp_apis(project_id: str) -> None:
  print(f"[1/3] Enabling BigQuery & Gemini Data Analytics APIs on '{project_id}'...")
  cmd = [
      "gcloud",
      "services",
      "enable",
      "bigquery.googleapis.com",
      "geminidataanalytics.googleapis.com",
      "cloudaicompanion.googleapis.com",
      f"--project={project_id}",
  ]
  try:
    subprocess.run(cmd, check=True)
  except Exception as exc:
    print(f"  -> Warning: gcloud services enable returned {exc}. Continuing via REST...")


def get_authorized_session() -> AuthorizedSession:
  credentials, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  if hasattr(credentials, "with_quota_project"):
    credentials = credentials.with_quota_project(PROJECT_ID)
  return AuthorizedSession(credentials)


def verify_thelook_dataset(
    session: AuthorizedSession, project_id: str, dataset_id: str
) -> tuple[str, set[str]]:
  print(f"[2/3] Verifying dataset '{project_id}.{dataset_id}' and its 7 tables...")
  bq_base = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}"
  ds_resp = session.get(f"{bq_base}/datasets/{dataset_id}")
  if ds_resp.status_code != 200 and dataset_id != "thelook_ecommerce":
    # Fallback check if `thelook_ecommerce` exists before `01_prepare_bigquery_data.py` was run
    alt_resp = session.get(f"{bq_base}/datasets/thelook_ecommerce")
    if alt_resp.status_code == 200:
      print(
          f"  -> Dataset '{dataset_id}' not found yet; falling back to '{project_id}.thelook_ecommerce'."
      )
      dataset_id = "thelook_ecommerce"
      ds_resp = alt_resp

  if ds_resp.status_code != 200:
    raise RuntimeError(
        f"Dataset '{project_id}.{dataset_id}' not found (HTTP {ds_resp.status_code}). "
        "Please run `python3 scripts/01_prepare_bigquery_data.py` first."
    )

  ds_location = ds_resp.json().get("location", "US")
  tables_resp = session.get(f"{bq_base}/datasets/{dataset_id}/tables?maxResults=50")
  tables_resp.raise_for_status()
  existing_tables = {
      t["tableReference"]["tableId"]
      for t in tables_resp.json().get("tables", [])
  }
  print(f"  -> Found dataset '{project_id}.{dataset_id}' (location: {ds_location})")
  print(f"  -> Discovered tables: {sorted(existing_tables)}")
  return dataset_id, existing_tables


def build_table_refs(
    project_id: str,
    dataset_id: str,
    existing_tables: set[str],
    desired_tables: list[str],
) -> list[dict[str, str]]:
  selected = [t for t in desired_tables if t in existing_tables]
  if not selected:
    selected = sorted(existing_tables)
  return [
      {"projectId": project_id, "datasetId": dataset_id, "tableId": tbl}
      for tbl in selected
  ]


def upsert_caa_data_agent(
    session: AuthorizedSession,
    project_id: str,
    agent_id: str,
    display_name: str,
    description: str,
    system_instruction: str,
    table_refs: list[dict[str, str]],
) -> str:
  agent_name = f"projects/{project_id}/locations/{LOCATION}/dataAgents/{agent_id}"
  gda_base = "https://geminidataanalytics.googleapis.com/v1"

  agent_body: dict[str, Any] = {
      "displayName": display_name,
      "description": description,
      "dataAnalyticsAgent": {
          "publishedContext": {
              "datasourceReferences": {
                  "bq": {"tableReferences": table_refs}
              },
              "systemInstruction": system_instruction,
          }
      },
  }

  check_resp = session.get(f"{gda_base}/{agent_name}")
  if check_resp.status_code == 200:
    print(f"  -> Updating existing Data Agent '{agent_name}' ({len(table_refs)} tables)...")
    op_resp = session.patch(
        f"{gda_base}/{agent_name}",
        params={"updateMask": "displayName,description,dataAnalyticsAgent.publishedContext"},
        json=agent_body,
    )
  else:
    print(f"  -> Creating new Data Agent '{agent_name}' ({len(table_refs)} tables)...")
    op_resp = session.post(
        f"{gda_base}/projects/{project_id}/locations/{LOCATION}/dataAgents",
        params={"dataAgentId": agent_id},
        json=agent_body,
    )

  if not op_resp.ok:
    raise RuntimeError(f"GDA API Error ({op_resp.status_code}): {op_resp.text}")

  op_data = op_resp.json()
  op_name = op_data.get("name", "")
  if op_data.get("done"):
    print(f"  -> Ready: {agent_name}")
    return agent_name

  for _ in range(30):
    time.sleep(2)
    poll = session.get(f"{gda_base}/{op_name}").json()
    if poll.get("done"):
      if "error" in poll:
        raise RuntimeError(f"Data Agent LRO Error: {json.dumps(poll['error'])}")
      print(f"  -> Provisioned: {agent_name}")
      return agent_name

  print(f"  -> LRO in progress ({op_name}): {agent_name}")
  return agent_name


def main() -> None:
  print("=================================================================")
  print(f" BigQuery CAA Provisioner for `{PROJECT_ID}.{DATASET_ID}`")
  print("=================================================================")
  enable_gcp_apis(PROJECT_ID)
  session = get_authorized_session()
  resolved_dataset, existing_tables = verify_thelook_dataset(
      session, PROJECT_ID, DATASET_ID
  )
  all_table_refs = build_table_refs(
      PROJECT_ID, resolved_dataset, existing_tables, THELOOK_TABLES
  )

  print("[3/3] Provisioning Single-Agent & 3 Domain-Scoped CAA Data Agents...")
  governed_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id=GOVERNED_AGENT_ID,
      display_name="TheLook eCommerce Governed Data Agent (KC + Glossary)",
      description=(
          f"Governed BigQuery CAA Agent for {resolved_dataset} with Korean Business Glossary "
          "(VIP 고객, 장바구니 이탈율, 상품 마진율, 환불률, 휴면 고객) and SQL mapping rules."
      ),
      system_instruction=GOVERNED_SYSTEM_INSTRUCTION.format(
          project=PROJECT_ID, dataset=resolved_dataset
      ),
      table_refs=all_table_refs,
  )
  baseline_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id=BASELINE_AGENT_ID,
      display_name="TheLook eCommerce Baseline Data Agent (Raw Schema Only)",
      description=(
          f"Baseline BigQuery CAA Agent for {resolved_dataset} without Business Glossary "
          "rules (for Before vs. After governance comparison)."
      ),
      system_instruction=BASELINE_SYSTEM_INSTRUCTION.format(dataset=resolved_dataset),
      table_refs=all_table_refs,
  )
  alias_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id="sales_kpi_ca_agent",
      display_name="Enterprise Sales & TheLook KPI Data Agent",
      description=(
          f"Alias Governed BigQuery CAA Agent for {resolved_dataset} with Korean Business Glossary."
      ),
      system_instruction=GOVERNED_SYSTEM_INSTRUCTION.format(
          project=PROJECT_ID, dataset=resolved_dataset
      ),
      table_refs=all_table_refs,
  )

  # Domain 1: Customer & Marketing CAA (4 tables)
  cust_mkt_refs = build_table_refs(
      PROJECT_ID, resolved_dataset, existing_tables, ["users", "events", "orders", "order_items"]
  )
  cust_mkt_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id=CUSTOMER_MARKETING_CA_ID,
      display_name="[Domain 1] TheLook Customer & Marketing CAA Agent",
      description=(
          "Customer CRM, segmentation (VIP/Churn/New), traffic source, and funnel cart abandonment "
          f"analytics agent scoped to `{resolved_dataset}` (`users`, `events`, `orders`, `order_items`)."
      ),
      system_instruction=CUSTOMER_MARKETING_SYSTEM_INSTRUCTION.format(
          project=PROJECT_ID, dataset=resolved_dataset
      ),
      table_refs=cust_mkt_refs,
  )

  # Domain 2: Product & Profitability CAA (3 tables)
  prod_prof_refs = build_table_refs(
      PROJECT_ID, resolved_dataset, existing_tables, ["products", "order_items", "orders"]
  )
  prod_prof_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id=PRODUCT_PROFITABILITY_CA_ID,
      display_name="[Domain 2] TheLook Product & Profitability CAA Agent",
      description=(
          "Product merchandising, category/brand gross margin, net revenue, and return/cancellation rate "
          f"analytics agent scoped to `{resolved_dataset}` (`products`, `order_items`, `orders`)."
      ),
      system_instruction=PRODUCT_PROFITABILITY_SYSTEM_INSTRUCTION.format(
          project=PROJECT_ID, dataset=resolved_dataset
      ),
      table_refs=prod_prof_refs,
  )

  # Domain 3: Supply Chain & Logistics CAA (5 tables)
  scm_refs = build_table_refs(
      PROJECT_ID,
      resolved_dataset,
      existing_tables,
      ["distribution_centers", "inventory_items", "order_items", "orders", "products"],
  )
  scm_name = upsert_caa_data_agent(
      session=session,
      project_id=PROJECT_ID,
      agent_id=SUPPLY_CHAIN_CA_ID,
      display_name="[Domain 3] TheLook Supply Chain & Logistics CAA Agent",
      description=(
          "Distribution center (DC), fulfillment/delivery lead-time, and unsold inventory holding cost "
          f"analytics agent scoped to `{resolved_dataset}` (`distribution_centers`, `inventory_items`, `order_items`, `orders`, `products`)."
      ),
      system_instruction=SUPPLY_CHAIN_SYSTEM_INSTRUCTION.format(
          project=PROJECT_ID, dataset=resolved_dataset
      ),
      table_refs=scm_refs,
  )

  print("\n✅ Provisioning Complete!")
  print(f"   - Dataset & Tables ({len(all_table_refs)}) : {PROJECT_ID}.{resolved_dataset}")
  print(f"   - Single Governed Agent   : {governed_name}")
  print(f"   - Single Baseline Agent   : {baseline_name}")
  print(f"   - Alias Agent             : {alias_name}")
  print(f"   - [Sub-Agent 1] Customer  : {cust_mkt_name} (tables: users, events, orders, order_items)")
  print(f"   - [Sub-Agent 2] Product   : {prod_prof_name} (tables: products, order_items, orders)")
  print(f"   - [Sub-Agent 3] Logistics : {scm_name} (tables: distribution_centers, inventory_items, order_items, orders, products)")
  print("   - Launch ADK Web UI       : ./run_adk_web.sh")


if __name__ == "__main__":
  main()
