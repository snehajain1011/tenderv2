from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on environment variables being set externally

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from persistence import ProcurementRepository
    from schema import Document

logger = logging.getLogger(__name__)

# Standard GSTIN format: 2-digit state code + 10-char PAN + 1-char entity + Z + 1 check digit
GSTIN_PATTERN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")

_RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
_RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST", "gst-insights-api.p.rapidapi.com")


@dataclass(frozen=True)
class GstinCheck:
    gstin: str
    legal_name: str
    is_valid: bool
    is_active: bool
    # "invalid"   → blocked immediately (bad/inactive GSTIN)
    # "flagged"   → blocked due to negative procurement history in DB
    # "no_gstin"  → no GSTIN found; foreign bidder or missing — flagged for review, not blocked
    # "clear"     → passes all pre-checks, proceed to criteria evaluation
    check_status: str
    rejection_reason: str


def extract_gstin(text: str) -> str | None:
    """Return the first GSTIN found in text, or None."""
    match = GSTIN_PATTERN.search(text)
    return match.group(0) if match else None


def validate_gstin_api(gstin: str) -> GstinCheck:
    """
    GATE 1 — Call the GST Insights RapidAPI to verify the GSTIN.

    Decision order (hard block at first failure):
      a. GSTIN structurally invalid or not found in GST records → block
      b. GSTIN found but status is not Active → block
      c. Both valid and active → return check_status="clear"
    """
    logger.info("[GSTIN] Calling validation API for GSTIN: %s", gstin)

    if _requests is None:
        logger.warning("[GSTIN] requests library not installed — skipping API check, failing open for %s", gstin)
        return GstinCheck(gstin=gstin, legal_name="", is_valid=True, is_active=True,
                          check_status="clear", rejection_reason="")

    url = f"https://{_RAPIDAPI_HOST}/validateGSTNumber/{gstin}"
    headers = {
        "x-rapidapi-key": _RAPIDAPI_KEY,
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "Content-Type": "application/json",
    }
    try:
        resp = _requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        logger.debug("[GSTIN] Raw API response for %s: %s", gstin, data)
    except Exception as exc:
        logger.warning("[GSTIN] API call failed for %s (%s) — failing open to avoid blocking on outage", gstin, exc)
        return GstinCheck(gstin=gstin, legal_name="", is_valid=True, is_active=True,
                          check_status="clear", rejection_reason="")

    info = data.get("data") or {}
    is_valid = bool(data.get("success")) and bool(info.get("isValid"))
    legal_name = info.get("legalName", "")
    gst_status = info.get("status", "Unknown")

    # ── GATE 1a: GSTIN validity ───────────────────────────────────────────────
    if not is_valid:
        logger.warning(
            "[GSTIN] BLOCKED — GSTIN %s is NOT valid (success=%s, isValid=%s). Bidder rejected immediately.",
            gstin, data.get("success"), info.get("isValid"),
        )
        return GstinCheck(
            gstin=gstin,
            legal_name=legal_name,
            is_valid=False,
            is_active=False,
            check_status="invalid",
            rejection_reason=(
                f"GSTIN {gstin} is not valid per GST authority records. "
                "The bid cannot be processed."
            ),
        )

    logger.info("[GSTIN] GSTIN %s is structurally valid. Legal name: '%s'", gstin, legal_name)

    # ── GATE 1b: Active status ────────────────────────────────────────────────
    is_active = bool(info.get("isActive"))
    if not is_active:
        logger.warning(
            "[GSTIN] BLOCKED — GSTIN %s (%s) is registered but status is '%s' (not Active). Bidder rejected immediately.",
            gstin, legal_name, gst_status,
        )
        return GstinCheck(
            gstin=gstin,
            legal_name=legal_name,
            is_valid=True,
            is_active=False,
            check_status="invalid",
            rejection_reason=(
                f"GSTIN {gstin} belongs to '{legal_name}' but is currently marked "
                f"'{gst_status}' by GST authority. Only Active GSTINs are eligible to bid."
            ),
        )

    logger.info("[GSTIN] GSTIN %s (%s) is Active. Gate 1 passed.", gstin, legal_name)
    return GstinCheck(
        gstin=gstin,
        legal_name=legal_name,
        is_valid=True,
        is_active=True,
        check_status="clear",
        rejection_reason="",
    )


def run_gstin_checks(
    bidder_docs: dict[str, list[Document]],
    repo: ProcurementRepository | None = None,
) -> dict[str, GstinCheck]:
    """
    Run the two-gate GSTIN pre-check for every bidder before criteria evaluation.

    Gate 1 — API validity (blocks immediately if GSTIN is missing, invalid, or inactive).
    Gate 2 — DB flag check (blocks if the vendor has a negative procurement history).

    Only bidders that clear both gates proceed to eligibility criteria evaluation.
    """
    results: dict[str, GstinCheck] = {}

    for bidder, docs in bidder_docs.items():
        logger.info("[GSTIN] ── Starting pre-check for bidder: '%s' ──", bidder)

        # ── Extract GSTIN from submitted documents ─────────────────────────────
        combined_text = "\n".join(doc.text for doc in docs)
        gstin = extract_gstin(combined_text)

        if not gstin:
            # No GSTIN found — may be a foreign/international bidder.
            # Flag for manual review rather than hard-block, so international
            # bids are not automatically rejected by an India-specific check.
            logger.warning(
                "[GSTIN] WARNING — No GSTIN found in documents submitted by '%s'. "
                "Bidder flagged for manual review (foreign bidder or missing GSTIN).",
                bidder,
            )
            results[bidder] = GstinCheck(
                gstin="",
                legal_name="",
                is_valid=False,
                is_active=False,
                check_status="no_gstin",
                rejection_reason=(
                    "No GSTIN was found in the submitted documents. "
                    "If this is a domestic bidder, a valid active GSTIN is required. "
                    "Foreign bidders should provide equivalent tax registration proof."
                ),
            )
            continue

        logger.info("[GSTIN] Found GSTIN '%s' in documents for bidder '%s'. Proceeding to Gate 1 (API validation).", gstin, bidder)

        # ── Gate 1: API validation ─────────────────────────────────────────────
        check = validate_gstin_api(gstin)
        if check.check_status != "clear":
            # Already logged inside validate_gstin_api
            results[bidder] = check
            continue

        # ── Gate 2: DB negative-history flag ──────────────────────────────────
        logger.info("[GSTIN] Gate 1 passed for '%s'. Checking procurement DB flag for GSTIN '%s'.", bidder, gstin)

        if repo is not None and repo.is_vendor_flagged(gstin):
            flag_reason = repo.get_vendor_flag_reason(gstin)
            logger.warning(
                "[GSTIN] BLOCKED — GSTIN '%s' (%s) is flagged in the procurement DB. "
                "Reason: %s. Bidder '%s' rejected at Gate 2.",
                gstin, check.legal_name, flag_reason, bidder,
            )
            results[bidder] = GstinCheck(
                gstin=gstin,
                legal_name=check.legal_name,
                is_valid=True,
                is_active=True,
                check_status="flagged",
                rejection_reason=(
                    f"Vendor GSTIN {gstin} ({check.legal_name}) has been flagged in "
                    f"procurement records: {flag_reason}. This vendor is not permitted to bid."
                ),
            )
            continue

        logger.info(
            "[GSTIN] CLEARED — '%s' (GSTIN %s, legal name '%s') passed both gates. "
            "Proceeding to eligibility criteria evaluation.",
            bidder, gstin, check.legal_name,
        )
        results[bidder] = check

    return results
