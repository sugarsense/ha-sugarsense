"""Constants for the Sugar Sense integration."""

from __future__ import annotations

DOMAIN = "sugarsense"
VERSION = "1.0.0"
DEFAULT_TITLE = "Sugar Sense"

API_BASE = "https://api.sugarsense.io/api/v1"
REQUEST_TIMEOUT_SECONDS = 20

CONF_SESSION_TOKEN = "session_token"
CONF_ACCOUNT_REF = "account_ref"

DEFAULT_PULL_SECONDS = 60
MIN_PULL_SECONDS = 30
MAX_PULL_SECONDS = 900

# Snapshot states (the server's contract).
STATE_OK = 0
STATE_PREMIUM_REQUIRED = 1
STATE_FOLLOWER_ONLY = 2
STATE_NO_SOURCE = 3

ISSUE_PREMIUM = "premium_required"
ISSUE_NO_SOURCE = "no_source"
ISSUE_FOLLOWER_ONLY = "follower_only"

APP_URL = "https://sugarsense.io/download"
