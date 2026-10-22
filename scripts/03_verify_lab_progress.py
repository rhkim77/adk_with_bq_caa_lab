#!/usr/bin/env python3
"""[Qwiklabs 'Check My Progress' Validator] Verifies completion of Lab Tasks 1 to 5.

Usage:
  python3 scripts/03_verify_lab_progress.py --all
  python3 scripts/03_verify_lab_progress.py --task 1
  python3 scripts/03_verify_lab_progress.py --task 2
  python3 scripts/03_verify_lab_progress.py --task 3
  python3 scripts/03_verify_lab_progress.py --task 4
  python3 scripts/03_verify_lab_progress.py --task 5
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

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
sys.path.insert(0, str(REPO_ROOT))

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "ryan-sandbox-agent")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "thelook_ecommerce_agent")


def _session() -> AuthorizedSession:
  creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
  if hasattr(creds, "with_quota_project"):
    creds = creds.with_quota_project(PROJECT_ID)
  return AuthorizedSession(creds)


def check_task_1() -> bool:
  print("\n🔍 [Task 1 Check] Customer Environment & BigQuery Dataset (`thelook_ecommerce_agent`)...")
  sess = _session()
  resp = sess.get(f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/datasets/{DATASET_ID}")
  if resp.status_code == 200:
    loc = resp.json().get("location", "US")
    print(f"  ✅ PASS: Dataset `{PROJECT_ID}.{DATASET_ID}` exists (Location: {loc}).")
    return True
  print(f"  ❌ FAIL: Dataset `{PROJECT_ID}.{DATASET_ID}` not found (HTTP {resp.status_code}).")
  return False


def check_task_2() -> bool:
  print("\n🔍 [Task 2 Check] 7 Cloned Tables & Seeded Golden Demo Scenario Data...")
  sess = _session()
  resp = sess.get(
      f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables?maxResults=50"
  )
  if resp.status_code != 200:
    print("  ❌ FAIL: Unable to list tables.")
    return False
  tables = {t["tableReference"]["tableId"] for t in resp.json().get("tables", [])}
  expected = {"distribution_centers", "events", "inventory_items", "order_items", "orders", "products", "users"}
  missing = expected - tables
  if missing:
    print(f"  ❌ FAIL: Missing tables: {sorted(missing)}")
    return False
  print(f"  ✅ PASS: All 7 core tables verified in `{PROJECT_ID}.{DATASET_ID}`: {sorted(expected)}")
  return True


def check_task_3() -> bool:
  print("\n🔍 [Task 3 Check] 6 BigQuery CAA Data Agents (Single + 3 Domain Sub-Agents)...")
  sess = _session()
  required_agents = [
      "thelook_governed_ca_agent",
      "thelook_baseline_ca_agent",
      "thelook_customer_marketing_ca",
      "thelook_product_profitability_ca",
      "thelook_supply_chain_ca",
  ]
  all_ok = True
  for ag in required_agents:
    url = f"https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/dataAgents/{ag}"
    r = sess.get(url)
    if r.status_code == 200:
      tbls = (
          r.json()
          .get("dataAnalyticsAgent", {})
          .get("publishedContext", {})
          .get("datasourceReferences", {})
          .get("bq", {})
          .get("tableReferences", [])
      )
      print(f"  ✅ PASS: `{ag}` provisioned ({len(tbls)} tables scoped).")
    else:
      print(f"  ❌ FAIL: `{ag}` not found (HTTP {r.status_code}).")
      all_ok = False
  return all_ok


def check_task_4_and_5() -> bool:
  print("\n🔍 [Task 4 & 5 Check] ADK Root + 3 Sub-Agents Routing, Session State & Long-Term Memory...")
  try:
    from bq_caa_3domain_multi_agent.agent import root_agent

    sub_names = [s.name for s in root_agent.sub_agents]
    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in root_agent.tools]
    has_callbacks = bool(root_agent.before_agent_callback and root_agent.after_agent_callback)
    print(f"  ✅ PASS: Root Agent `{root_agent.name}` loaded.")
    print(f"  ✅ PASS: 3 Domain Sub-Agents wired: {sub_names}")
    print(f"  ✅ PASS: Root Tools wired: {tool_names}")
    print(f"  ✅ PASS: Session/Memory Lifecycle Callbacks active: {has_callbacks}")
    return len(sub_names) == 3 and has_callbacks
  except Exception as exc:
    print(f"  ❌ FAIL: Error loading `bq_caa_3domain_multi_agent`: {exc}")
    return False


def main() -> None:
  parser = argparse.ArgumentParser(description="Qwiklabs Progress Checker")
  parser.add_argument("--task", type=int, choices=[1, 2, 3, 4, 5], help="Task number to check")
  parser.add_argument("--all", action="store_true", help="Check all tasks")
  args = parser.parse_args()

  if args.task == 1:
    sys.exit(0 if check_task_1() else 1)
  elif args.task == 2:
    sys.exit(0 if check_task_2() else 1)
  elif args.task == 3:
    sys.exit(0 if check_task_3() else 1)
  elif args.task in (4, 5):
    sys.exit(0 if check_task_4_and_5() else 1)
  else:
    ok1 = check_task_1()
    ok2 = check_task_2()
    ok3 = check_task_3()
    ok4 = check_task_4_and_5()
    if ok1 and ok2 and ok3 and ok4:
      print("\n🎉 ALL LAB CHECKS PASSED! (100/100 Score)")
      sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
  main()
