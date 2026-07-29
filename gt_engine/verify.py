"""GT-enhanced verification gate - ADVISORY only (brief §10).

When the model claims done (end_turn), the agent asks GT - via a synthetic
submit-boundary event through the SAME bridge pipeline - whether
submit_refusal / syntax_result evidence exists. If it does and pushbacks
remain, the agent spends ONE of its existing pushbacks delivering that
evidence as the nudge text. No new stop states, no blocking: with no evidence
(or any fault) the stock verify gate proceeds unchanged.
"""
from __future__ import annotations


def submit_evidence(bridge) -> str | None:
    """Evidence text to use as a pushback nudge, or None (the common case).

    Never raises; a None bridge or any GT fault abstains.
    """
    if bridge is None:
        return None
    try:
        return bridge.submit_probe()
    except Exception:  # noqa: BLE001 - advisory: GT must never block completion
        return None
