
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scraper entrypoint with resilient cache handling and atomic writes.

- load_cache(): tolerant to missing/empty/invalid JSON
- save_cache(): atomic write to prevent truncated cache in CI
- main(): integrates safe cache usage and basic sanity checks

Replace `scrape()` with your actual scraping logic.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

# You can override via env, e.g. in GitHub Actions:
#   NEWS_CACHE_PATH="data/cache-${{ github.run_id }}.json"
CACHE_PATH = os.environ.get("NEWS_CACHE_PATH", "data/cache.json")

# Optional: fail the build if scrape produced 0 articles (set to '1' to enforce)
FAIL_ON_EMPTY = os.environ.get("FAIL_ON_EMPTY", "0") == "1"


# ------------------------------------------------------------------------------
# Utilities: logging
# ------------------------------------------------------------------------------

def log_info(msg: str) -> None:
    print(f"[info] {msg}", flush=True)


def log_warn(msg: str) -> None:
    print(f"[warn] {msg}", flush=True)


def log_error(msg: str) -> None:
    print(f"[error] {msg}", flush=True)


# ------------------------------------------------------------------------------
# Cache helpers
# ------------------------------------------------------------------------------

def load_cache(default: Any = None, path: str = CACHE_PATH) -> Any:
    """
    Load JSON cache safely.
    Returns `default` (or `{}`) if file is missing, empty, or invalid JSON.
    """
    if default is None:
        default = {}

    if not os.path.exists(path):
        log_info(f"Cache not found at {path}; using default.")
        return default

    try:
        size = os.path.getsize(path)
        if size == 0:
            log_warn(f"Cache at {path} is empty (0 bytes); using default.")
            return default

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except json.JSONDecodeError:
        log_warn(f"Invalid JSON in {path}; using default cache.")
        return default
    except OSError as e:
        log_warn(f"Could not read {path}: {e}; using default cache.")
        return default


def save_cache(data: Any, path: str = CACHE_PATH) -> None:
    """
    Atomically write JSON to disk to avoid truncated/partial files in CI.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".cache-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)  # atomic on POSIX & modern Windows
        log_info(f"Wrote cache atomically to {path} ({len(json.dumps(data))} bytes).")
    except Exception as e:
        log_error(f"Failed to write cache to {path}: {e}")
        # Best effort cleanup; don't raise further to avoid masking the real issue
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise
    finally:
        # If os.replace succeeded, tmp_path won't exist; ignore errors.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


# ------------------------------------------------------------------------------
# Example scraper (replace with your real logic)
# ------------------------------------------------------------------------------

def scrape() -> Dict[str, Any]:
    """
    Example scraper that returns a dict with an 'articles' list.
    Replace with your real scraping logic.
    """
    # Simulate network work
    time.sleep(0.3)

    # Return shape that your app expects; here we use a simple example
    result = {
        "generated_at": int(time.time()),
        "source": "example",
        "articles": [
            {
                "id": "example-1",
                "title": "Hello World",
                "url": "https://example.com/hello",
                "published_at": "2026-03-23T12:00:00Z",
            }
        ],
    }
    return result


def validate_payload(payload: Any) -> bool:
    """
    Quick sanity checks: payload must be a dict with a list under 'articles'.
    Customize to your schema.
    """
    if not isinstance(payload, dict):
        log_warn("Payload is not a dict.")
        return False
    if "articles" not in payload:
        log_warn("Payload missing 'articles' key.")
        return False
    if not isinstance(payload["articles"], list):
        log_warn("'articles' is not a list.")
        return False
    return True


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

def main() -> int:
    log_info("Starting scraper.")

    # Load existing cache safely (returns {} by default)
    existing = load_cache({})
    if not isinstance(existing, dict):
        log_warn("Existing cache is not a dict; resetting to {}.")
        existing = {}

    # Perform scraping
    try:
        new_data = scrape()
    except Exception as e:
        log_error(f"Scrape failed: {e}")
        # Keep existing cache; fail the process so CI signals error
        return 1

    # Validate new data
    if not validate_payload(new_data):
        log_warn("New data failed validation; keeping existing cache.")
        if FAIL_ON_EMPTY:
            log_error("FAIL_ON_EMPTY is set; failing the build.")
            return 1
        return 0

    # Optionally prevent saving if empty results
    if len(new_data.get("articles", [])) == 0:
        log_warn("Scrape produced 0 articles.")
        if FAIL_ON_EMPTY:
            log_error("FAIL_ON_EMPTY is set; failing the build.")
            return 1
        else:
            log_warn("Keeping existing cache (not overwriting with empty).")
            return 0

    # Merge strategy (optional): you can customize merging behavior
    merged = new_data  # simple replacement; or implement dedup/merge with `existing`

    # Persist atomically
    try:
        save_cache(merged)
    except Exception:
        # save_cache already logged; ensure CI gets a failure code
        return 1

    log_info("Scraper completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
