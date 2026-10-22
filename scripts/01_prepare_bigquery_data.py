#!/usr/bin/env python3
"""[Task 1 & 2] Prepares Customer BigQuery Dataset (`thelook_ecommerce_agent`), Clones Public Data, and Seeds Golden Demo Scenarios.

Works via BigQuery REST API (`bigquery.googleapis.com/bigquery/v2`) using Keyless ADC (`google.auth`),
so it runs reliably even on machines without the `bq` CLI installed.

Steps performed:
  1. Creates BigQuery Dataset `{PROJECT_ID}.{DATASET_ID}` (Default: `thelook_ecommerce_agent`, Location: `US`) if not present.
  2. Executes `sql/01_clone_public_thelook.sql` to clone the 7 core tables from `bigquery-public-data.thelook_ecommerce`.
  3. Executes `sql/02_seed_demo_scenarios.sql` to inject fresh, deterministic golden demo data across all 3 domains:
     - Domain 1 (Customer & Marketing): Recent VIP customers (> $500) & Cart Abandonment sessions.
     - Domain 2 (Product & Profitability): High-margin (>56%) Women Outerwear products with Return/Cancel spikes.
     - Domain 3 (Supply Chain & Logistics): 6-day delivery lead-time bottleneck on DC #2 (Chicago IL) & unsold inventory.
  4. Verifies and prints table row counts.
"""

from __future__ import annotations

import os
from pathlib import Path
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

REPO_ROOT = Path(__file__).resolve().parent.parent

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
if PROJECT_ID in ("", "your-gcp-project-id"):
  PROJECT_ID = "ryan-sandbox-agent"

DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "US")

CLONE_SQL_PATH = REPO_ROOT / "sql" / "01_clone_public_thelook.sql"
SEED_SQL_PATH = REPO_ROOT / "sql" / "02_seed_demo_scenarios.sql"

EXPECTED_TABLES = [
    "distribution_centers",
    "products",
    "users",
    "orders",
    "order_items",
    "inventory_items",
    "events",
]


def get_authorized_session() -> AuthorizedSession:
  credentials, _ = google.auth.default(
      scopes=["https://www.googleapis.com/auth/cloud-platform"]
  )
  if hasattr(credentials, "with_quota_project"):
    credentials = credentials.with_quota_project(PROJECT_ID)
  return AuthorizedSession(credentials)


def ensure_dataset_exists(
    session: AuthorizedSession,
    project_id: str,
    dataset_id: str,
    location: str,
) -> None:
  print(f"[1/4] Ensuring BigQuery Dataset `{project_id}.{dataset_id}` (location: {location})...")
  bq_base = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}"
  check = session.get(f"{bq_base}/datasets/{dataset_id}")
  if check.status_code == 200:
    existing_loc = check.json().get("location", location)
    print(f"  -> Dataset `{project_id}.{dataset_id}` already exists (location: {existing_loc}).")
    return

  body = {
      "datasetReference": {
          "projectId": project_id,
          "datasetId": dataset_id,
      },
      "location": location,
      "friendlyName": "TheLook eCommerce Agentic Demo Dataset",
      "description": (
          "Cloned from bigquery-public-data.thelook_ecommerce and augmented with "
          "3-Domain Golden Demo Scenarios for BigQuery CAA + Google ADK Multi-Agent Lab."
      ),
  }
  resp = session.post(f"{bq_base}/datasets", json=body)
  if not resp.ok:
    raise RuntimeError(
        f"Failed to create dataset `{project_id}.{dataset_id}` (HTTP {resp.status_code}): {resp.text}"
    )
  print(f"  -> Created dataset `{project_id}.{dataset_id}` in `{location}`.")


def run_bq_sql_statement(
    session: AuthorizedSession,
    project_id: str,
    location: str,
    sql: str,
) -> dict[str, Any]:
  """Executes a Standard SQL statement via BigQuery `jobs.query` REST API and polls until complete."""
  bq_base = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}"
  payload = {
      "query": sql,
      "useLegacySql": False,
      "location": location,
      "timeoutMs": 60000,
  }
  resp = session.post(f"{bq_base}/queries", json=payload, timeout=120)
  if not resp.ok:
    raise RuntimeError(f"BigQuery SQL Error ({resp.status_code}): {resp.text}\nSQL:\n{sql[:300]}")

  data = resp.json()
  job_ref = data.get("jobReference", {})
  job_id = job_ref.get("jobId")
  job_loc = job_ref.get("location", location)

  while not data.get("jobComplete", False):
    time.sleep(1.5)
    poll = session.get(
        f"{bq_base}/queries/{job_id}",
        params={"location": job_loc, "timeoutMs": 30000},
    )
    poll.raise_for_status()
    data = poll.json()

  if "errors" in data and data["errors"]:
    raise RuntimeError(f"BigQuery Job Failed: {data['errors']}")
  return data


def parse_sql_statements(sql_file: Path, project_id: str, dataset_id: str) -> list[str]:
  raw = sql_file.read_text(encoding="utf-8")
  rendered = raw.replace("__PROJECT_ID__", project_id).replace("__DATASET_ID__", dataset_id)
  statements: list[str] = []
  for chunk in rendered.split(";"):
    lines = [
        line for line in chunk.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    cleaned = "\n".join(lines).strip()
    if cleaned:
      statements.append(cleaned)
  return statements


def verify_row_counts(
    session: AuthorizedSession,
    project_id: str,
    dataset_id: str,
    location: str,
) -> None:
  print(f"[4/4] Verifying 7 tables and row counts in `{project_id}.{dataset_id}`...")
  union_queries = [
      f"SELECT '{tbl}' AS table_name, COUNT(*) AS total_rows, "
      f"COUNTIF({'order_id' if tbl == 'orders' else 'id'} >= 9900000) AS seeded_demo_rows "
      f"FROM `{project_id}.{dataset_id}.{tbl}`"
      for tbl in EXPECTED_TABLES
  ]
  full_sql = "\nUNION ALL\n".join(union_queries) + "\nORDER BY table_name"
  res = run_bq_sql_statement(session, project_id, location, full_sql)

  print("\n  ┌──────────────────────────┬──────────────┬───────────────────┐")
  print("  │ Table Name               │ Total Rows   │ Seeded Demo Rows  │")
  print("  ├──────────────────────────┼──────────────┼───────────────────┤")
  for row in res.get("rows", []):
    vals = [f["v"] for f in row.get("f", [])]
    if len(vals) == 3:
      print(f"  │ {vals[0]:<24} │ {int(vals[1]):>12,} │ {int(vals[2]):>17,} │")
  print("  └──────────────────────────┴──────────────┴───────────────────┘")


def main() -> None:
  print("======================================================================")
  print(f" BigQuery Data Preparation for `{PROJECT_ID}.{DATASET_ID}` ({BQ_LOCATION})")
  print("======================================================================")
  session = get_authorized_session()
  ensure_dataset_exists(session, PROJECT_ID, DATASET_ID, BQ_LOCATION)

  print(f"[2/4] Cloning 7 tables from `bigquery-public-data.thelook_ecommerce` -> `{PROJECT_ID}.{DATASET_ID}`...")
  clone_stmts = parse_sql_statements(CLONE_SQL_PATH, PROJECT_ID, DATASET_ID)
  for idx, stmt in enumerate(clone_stmts, 1):
    tbl_name = EXPECTED_TABLES[idx - 1] if idx - 1 < len(EXPECTED_TABLES) else f"statement_{idx}"
    print(f"  -> [{idx}/{len(clone_stmts)}] Cloning table `{tbl_name}`...")
    run_bq_sql_statement(session, PROJECT_ID, BQ_LOCATION, stmt)

  print(f"[3/4] Seeding 3-Domain Golden Demo Scenario Data (`sql/02_seed_demo_scenarios.sql`)...")
  seed_stmts = parse_sql_statements(SEED_SQL_PATH, PROJECT_ID, DATASET_ID)
  for idx, stmt in enumerate(seed_stmts, 1):
    first_line = stmt.splitlines()[0][:70]
    print(f"  -> [{idx}/{len(seed_stmts)}] Executing: {first_line}...")
    run_bq_sql_statement(session, PROJECT_ID, BQ_LOCATION, stmt)

  verify_row_counts(session, PROJECT_ID, DATASET_ID, BQ_LOCATION)
  print(f"\n✅ Dataset `{PROJECT_ID}.{DATASET_ID}` is ready for BigQuery CAA & ADK Multi-Agent Lab!")


if __name__ == "__main__":
  main()
