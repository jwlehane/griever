#!/usr/bin/env python3
"""Smoke-test Griever's public HTTP flow for one or more addresses.

Usage:
    python tools/smoke_addresses.py --base https://tax-grieve-app-529334528547.us-east5.run.app \
        "33 Cedar Heights, Rhinebeck, NY" "60 Orchard St, Kingston, NY"
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests


def _events(resp):
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        yield json.loads(line[6:])


def smoke_address(base_url: str, address: str, timeout: int) -> bool:
    base_url = base_url.rstrip("/")
    print(f"\n== {address} ==")

    search = requests.post(
        f"{base_url}/search_property",
        data={"address": address},
        timeout=timeout,
    )
    print(f"search_property: {search.status_code}")
    search.raise_for_status()
    payload = search.json()
    if payload.get("status") != "success":
        print(f"  ERROR: {payload.get('message')}")
        return False

    subject = payload["subject"]
    subject_id = payload["subject_id"]
    print(f"  subject: {subject.get('address')} ({subject.get('sbl')})")

    verified = []
    rendered = False
    started = time.time()
    with requests.post(
        f"{base_url}/report",
        data={
            "address": address,
            "subject_id": subject_id,
            "force_verify": "true",
            "condition": "average",
        },
        stream=True,
        timeout=(10, timeout),
    ) as report:
        print(f"report: {report.status_code}")
        report.raise_for_status()
        for event in _events(report):
            status = event.get("status")
            if status == "verified":
                comp = event.get("comp") or {}
                verified.append(comp)
                print(f"  verified {comp.get('grade')} {comp.get('similarity_score')}: {comp.get('address')}")
            elif status in {"no_comps", "error"}:
                print(f"  {status.upper()}: {event.get('message')}")
                return False
            elif status == "render_ui":
                rendered = True
                break

    print(f"  elapsed: {time.time() - started:.1f}s, verified comps: {len(verified)}, rendered: {rendered}")
    return rendered and len(verified) >= 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080", help="Base URL for the app")
    parser.add_argument("--timeout", type=int, default=180, help="Per-address report timeout in seconds")
    parser.add_argument("addresses", nargs="+")
    args = parser.parse_args()

    ok = True
    for address in args.addresses:
        try:
            ok = smoke_address(args.base, address, args.timeout) and ok
        except Exception as exc:
            ok = False
            print(f"  ERROR: {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
