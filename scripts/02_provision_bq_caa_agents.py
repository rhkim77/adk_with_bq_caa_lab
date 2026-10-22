#!/usr/bin/env python3
"""Wrapper entry point for `provision_bq_caa_demo.py` inside `scripts/`."""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from provision_bq_caa_demo import main

if __name__ == "__main__":
  main()
