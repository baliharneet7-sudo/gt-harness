"""Evidence-aware context management for nano-harness.

``smart_truncate`` preserves nano's exact two-phase, char-metric truncation
(agent.py:_truncate_if_needed) as the base behavior. The single change is
phase 1's treatment of tool_result blocks that carry delivered GT evidence:

    SEALED => SEEN (FIX E, structural): a block containing ANY delivered
    span is EXEMPT from phase-1 truncation — never merely ranked last. A
    delivery sealed at the end of iteration N must still be present when the
    model reads iteration N+1; a sealed-but-never-seen delivery would be the
    F1 lie class (the seal attests the model received the bytes). Overflow
    falls through to phase 2 (tool_use input shrinking) and ultimately to
    nano's provider-side token cap — accepted cost: deliveries are <=4000
    chars and <=1 per observation.

Phase 2 (shrinking >200-char string args of past tool_use blocks) is kept
verbatim - giant edit_file `new` strings would otherwise re-inflate every
request. When GT never delivered anything there are no exemptions, so
behavior (including transcript truncation events) is byte-identical to the
original oldest-first pass (GT-off byte identity).
"""
from __future__ import annotations

from typing import Any

_VERIFIED = "VERIFIED"


def _block_evidence_rank(content: str, spans) -> int:
    """0 = no GT evidence, 1 = evidence below VERIFIED, 2 = VERIFIED evidence."""
    rank = 0
    for span in spans:
        probe = span.text.strip()
        if probe and probe in content:
            if span.tier == _VERIFIED:
                return 2
            rank = 1
    return rank


def smart_truncate(
    messages: list[dict[str, Any]],
    transcript: list[dict[str, Any]],
    *,
    char_budget: int,
    delivered_spans=(),
) -> None:
    # --- identical char metric to Agent._truncate_if_needed ---
    def total_chars() -> int:
        n = 0
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                n += len(c)
            elif isinstance(c, list):
                for b in c:
                    n += len(b.get("text", "")) + len(b.get("content", ""))
                    for v in (b.get("input") or {}).values():
                        if isinstance(v, str):
                            n += len(v)
        return n

    if total_chars() <= char_budget:
        return

    # Phase 1: drop tool_result content - evidence-bearing blocks are EXEMPT
    # (sealed => seen): any block containing a delivered span is never
    # phase-1 truncated, whatever its tier. Evidence-free blocks keep the
    # stock oldest-first order; with no delivered spans NOTHING is exempt
    # and this is byte-identical to the stock pass.
    candidates: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if b.get("type") == "tool_result" and not str(
                    b.get("content", "")).startswith("[truncated"):
                if _block_evidence_rank(str(b.get("content", "")),
                                        delivered_spans) > 0:
                    continue  # sealed => seen: exempt, fall through to phase 2
                candidates.append(b)

    for b in candidates:
        original_len = len(b.get("content", ""))
        b["content"] = f"[truncated - {original_len} chars dropped]"
        transcript.append({"type": "truncation",
                           "tool_use_id": b.get("tool_use_id"),
                           "dropped_chars": original_len})
        if total_chars() <= char_budget:
            return

    # Phase 2: still over budget - shrink the largest string args of past
    # tool_use blocks (identical to the original).
    for m in messages:
        if not isinstance(m.get("content"), list):
            continue
        for b in m["content"]:
            if b.get("type") != "tool_use":
                continue
            inp = b.get("input") or {}
            for k, v in list(inp.items()):
                if isinstance(v, str) and len(v) > 200 and not v.startswith(
                        "[truncated"):
                    inp[k] = f"[truncated - {len(v)} chars dropped]"
                    transcript.append({"type": "truncation",
                                       "tool_use_id": b.get("id"),
                                       "dropped_chars": len(v)})
                    if total_chars() <= char_budget:
                        return
