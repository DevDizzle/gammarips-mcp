#!/usr/bin/env python3
"""
Dev/ops tool: mint or revoke a GammaRips MCP API key in Firestore.

This mirrors exactly what the webapp (Phase 3) will do server-side — it exists
so we can test ENFORCE mode and issue the owner's own key before the webapp UI
ships. Requires ADC with Firestore WRITE (your gcloud identity), NOT the MCP
service account (which is read-only by design).

Key model (docs/MCP-V3-SPEC.md §3.1):
  raw key   = "gr_live_" + 32 hex chars   (shown ONCE, never stored)
  doc id    = sha256(raw key)             (collection `mcp_api_keys`)
  doc body  = {uid, tier, status, created_at, label?}

Usage:
  PROJECT_ID=profitscout-fida8 python scripts/issue_api_key.py issue --uid <uid> [--tier pro] [--label "owner"]
  PROJECT_ID=profitscout-fida8 python scripts/issue_api_key.py revoke --key gr_live_xxx
  PROJECT_ID=profitscout-fida8 python scripts/issue_api_key.py revoke --hash <sha256>
"""

import argparse
import hashlib
import os
import secrets
import sys

from google.cloud import firestore

PROJECT = os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT_ID") or "profitscout-fida8"
COLLECTION = "mcp_api_keys"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue(uid: str, tier: str, label: str | None) -> int:
    raw = "gr_live_" + secrets.token_hex(16)
    db = firestore.Client(project=PROJECT)
    db.collection(COLLECTION).document(hash_key(raw)).set(
        {
            "uid": uid,
            "tier": tier,
            "status": "active",
            "label": label,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )
    print("API key issued (store it now — it is NOT recoverable):\n")
    print(f"  {raw}\n")
    print(f"  uid={uid} tier={tier} label={label or '-'}")
    print(f"  doc={COLLECTION}/{hash_key(raw)}")
    return 0


def revoke(raw: str | None, key_hash: str | None) -> int:
    h = key_hash or (hash_key(raw) if raw else None)
    if not h:
        print("provide --key or --hash", file=sys.stderr)
        return 2
    db = firestore.Client(project=PROJECT)
    ref = db.collection(COLLECTION).document(h)
    if not ref.get().exists:
        print(f"no key doc {COLLECTION}/{h}", file=sys.stderr)
        return 1
    ref.update({"status": "revoked", "revoked_at": firestore.SERVER_TIMESTAMP})
    print(f"revoked {COLLECTION}/{h}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("issue")
    pi.add_argument("--uid", required=True)
    pi.add_argument("--tier", default="pro")
    pi.add_argument("--label")
    pr = sub.add_parser("revoke")
    pr.add_argument("--key")
    pr.add_argument("--hash")
    a = p.parse_args()
    if a.cmd == "issue":
        return issue(a.uid, a.tier, a.label)
    return revoke(a.key, a.hash)


if __name__ == "__main__":
    raise SystemExit(main())
