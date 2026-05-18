"""PII-safe logging helpers.

Log lines end up in Cloud Logging, indexed and retained. Full addresses tie
a user to a property and become a privacy issue at scale, so we mask them
before they leave the process.

Usage:
    from app.logging_safe import safe_addr
    print(f"verifying {safe_addr(full_address)}")
"""

from __future__ import annotations

import hashlib
import re


def safe_addr(text: str | None) -> str:
    """Return a masked, deterministic representation of an address.

    The first 3 chars (typically the house number) and a short hash of the
    remainder are kept so a developer reading logs can distinguish two
    addresses without recovering either. Hash is truncated SHA-1; not for
    cryptographic use, just for collision-resistant masking.
    """
    if not text:
        return "<empty>"
    s = str(text).strip()
    if not s:
        return "<empty>"
    head = s[:3]
    digest = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
    return f"{head}***{digest}"


def safe_owner(name: str | None) -> str:
    """Owner names are higher-sensitivity PII than addresses (they link a
    person to a tax case). Don't leak any of the name; just confirm length."""
    if not name:
        return "<no-owner>"
    return f"<owner:{len(str(name))}c>"
