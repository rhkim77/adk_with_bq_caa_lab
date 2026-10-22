"""Initializes macOS System Keychain SSL truststore, certifi fallback, and GCP project before loading ADK agent."""

import os

os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")
os.environ.setdefault("GOOGLE_API_USE_MTLS_ENDPOINT", "never")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

if os.environ.get("GOOGLE_CLOUD_PROJECT") in (None, "", "your-gcp-project-id"):
  os.environ["GOOGLE_CLOUD_PROJECT"] = "ryan-sandbox-agent"

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

from . import agent
