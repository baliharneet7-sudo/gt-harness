"""Verbatim, line-level requirement ledger for the persistent task plan.

``task_contract.extract_task_contract`` is precision-biased: it merges prose
into sentences, drops lines that carry no directive verb, and truncates rows at
500 characters.  Measured on the awilix prompt it produced 13 obligations in
which the Assumptions block was glued into two run-on rows -- the requirement
the run actually missed (the parent container's singletons are not
reinitialized) sat mid-sentence inside one of them -- and the four ``Api:``
result-shape lines vanished entirely.  A ledger row is therefore ONE SOURCE
LINE, kept byte for byte, so a completeness miss is a row a reader can point at.

This module never reads tests, the fail-to-pass list, or anything under the
benchmark harness.  Its only input is the prompt the agent already receives.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from ..task_contract import (
    Obligation,
    TaskContract,
    TaskMode,
    _clean,
    _is_workflow_noise,
    _key,
    _leaks_test_identity,
    _subjects,
    _task_mode,
    _typed_predicates,
    significant_tokens,
)

_FENCE_RE = re.compile(r"^\s*```")
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(?P<text>.+?)\s*$")
_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*(?P<hash>.+?)|\*\*(?P<bold>[^*]+)\*\*)\s*:?\s*$"
)
_LABEL_RE = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z /_-]{2,40}):\s*$")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
# Sentence boundary INSIDE one physical line. Splitting here is lossless: the
# pieces rejoin with a single space to reproduce the cleaned line, and the test
# suite pins that. Merging ACROSS lines is what produced the awilix miss and is
# never done. A period with no following space (result.metrics.database.level)
# is not a boundary.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(])")

# Sections whose content is context rather than requirement. The same three
# names ``task_contract._normative_issue_text`` drops, so the two views of the
# prompt cannot disagree about what is normative.
NON_NORMATIVE_SECTIONS = frozenset({"background", "baseline", "cost model"})

# A line that is only brackets, commas or operators carries no requirement even
# inside a normative region (the closing "})" of an API sketch).
_STRUCTURAL_ONLY_RE = re.compile(r"^[\s{}()\[\];,.:=<>|&+*/\\-]*$")

MAX_ROW_CHARS = 500


@dataclass(frozen=True)
class LedgerRow:
    """One normative source line, verbatim."""

    row_id: str
    text: str
    section: str
    line_no: int
    shape: str
    sentence_index: int = 0
    subjects: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()
    obligation_ids: tuple[str, ...] = ()

    @property
    def is_ledger_only(self) -> bool:
        """True when no extracted obligation covers this line."""
        return not self.obligation_ids

    def as_dict(self) -> dict:
        return {
            "row_id": self.row_id,
            "text": self.text,
            "section": self.section,
            "line_no": self.line_no,
            "shape": self.shape,
            "sentence_index": self.sentence_index,
            "subjects": list(self.subjects),
            "obligation_ids": list(self.obligation_ids),
        }


@dataclass(frozen=True)
class Ledger:
    rows: tuple[LedgerRow, ...] = ()
    skipped: tuple[tuple[int, str], ...] = ()
    fenced_lines: int = 0

    def __iter__(self):
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def ledger_only(self) -> tuple[LedgerRow, ...]:
        return tuple(row for row in self.rows if row.is_ledger_only)

    def by_id(self, row_id: str) -> LedgerRow | None:
        for row in self.rows:
            if row.row_id == row_id:
                return row
        return None

    def counts(self) -> dict[str, int]:
        return {
            "rows": len(self.rows),
            "linked_rows": sum(1 for row in self.rows if row.obligation_ids),
            "ledger_only_rows": len(self.ledger_only),
            "skipped": len(self.skipped),
            "fenced_lines": self.fenced_lines,
        }


def row_id_for(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    return "req-" + digest[:12]


def _section_name(line: str) -> str | None:
    """Return a normalised section label when the line is a heading, else None."""
    heading = _HEADING_RE.match(line)
    if heading:
        name = heading.group("hash") or heading.group("bold") or ""
        return _clean(name).strip("#*: ").lower()
    label = _LABEL_RE.match(line)
    if label:
        return _clean(label.group("label")).lower()
    return None


def _shape(raw: str) -> str:
    if _BULLET_RE.match(raw):
        return "bullet"
    if raw[:1].isspace():
        return "indented"
    return "prose"


def _split_sentences(line_text: str) -> tuple[str, ...]:
    """Sentence pieces of ONE physical line, each kept verbatim.

    Lossless by construction: ``" ".join(_split_sentences(x)) == x`` for any
    cleaned line, which the suite pins. This is the only place a row is finer
    than a source line, and it never crosses a line boundary.
    """
    parts = tuple(part for part in _SENTENCE_SPLIT_RE.split(line_text) if part)
    return parts or (line_text,)


def _carries_requirement(text: str) -> bool:
    if _STRUCTURAL_ONLY_RE.match(text):
        return False
    return bool(_IDENTIFIER_RE.search(text))


def build_requirement_ledger(
    issue_text: str, contract: TaskContract | None = None
) -> Ledger:
    """Split the prompt into verbatim normative lines.

    Every non-blank line outside a fenced block and outside a non-normative
    section becomes a row unless it is a heading, a duplicate, workflow noise,
    structurally empty, or a line that leaks test identity.  Bullet markers are
    stripped from the stored text (they are syntax, not requirement) and runs of
    whitespace are collapsed; nothing else is rewritten -- no sentence
    splitting, no merging, no truncation.
    """
    rows: list[LedgerRow] = []
    skipped: list[tuple[int, str]] = []
    seen: set[str] = set()
    section = ""
    fenced = False
    fenced_lines = 0

    for line_no, raw in enumerate((issue_text or "").splitlines(), start=1):
        if _FENCE_RE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            fenced_lines += 1
            continue
        if not raw.strip():
            continue
        name = _section_name(raw)
        if name is not None:
            section = name
            continue
        if section in NON_NORMATIVE_SECTIONS:
            skipped.append((line_no, "non_normative_section"))
            continue

        bullet = _BULLET_RE.match(raw)
        line_text = _clean(bullet.group("text") if bullet else raw)
        if not line_text:
            continue
        shape = _shape(raw)
        for sentence_index, text in enumerate(_split_sentences(line_text)):
            if len(text) > MAX_ROW_CHARS:
                # Truncating would make the row non-verbatim, which is the exact
                # defect this ledger exists to remove. Record it instead.
                skipped.append((line_no, "row_too_long"))
                continue
            if not _carries_requirement(text):
                skipped.append((line_no, "structural_only"))
                continue
            if _is_workflow_noise(text):
                skipped.append((line_no, "workflow_noise"))
                continue
            if _leaks_test_identity(text):
                skipped.append((line_no, "leaks_test_identity"))
                continue
            key = _key(text)
            if not key or key in seen:
                skipped.append((line_no, "duplicate"))
                continue
            seen.add(key)
            rows.append(
                LedgerRow(
                    row_id=row_id_for(text),
                    text=text,
                    section=section,
                    line_no=line_no,
                    shape=shape,
                    sentence_index=sentence_index,
                    subjects=_subjects(text),
                    tokens=significant_tokens(text),
                )
            )

    if contract is not None:
        rows = _link_obligations(rows, contract)
    return Ledger(rows=tuple(rows), skipped=tuple(skipped), fenced_lines=fenced_lines)


def _link_obligations(
    rows: list[LedgerRow], contract: TaskContract
) -> list[LedgerRow]:
    """Attach the obligations each row is covered by, if any.

    An obligation covers a row when one normalised text contains the other.
    ``extract_task_contract`` merges lines, so one obligation routinely covers
    several rows -- that is exactly the merge this ledger undoes, and the link
    is what lets a merged obligation's evidence credit each line it swallowed.
    """
    obligation_keys = [
        (obligation.obligation_id, _key(obligation.text))
        for obligation in contract.obligations
    ]
    linked: list[LedgerRow] = []
    for row in rows:
        row_key = _key(row.text)
        matches = tuple(
            sorted(
                obligation_id
                for obligation_id, obligation_key in obligation_keys
                if obligation_key
                and (row_key in obligation_key or obligation_key in row_key)
            )
        )
        # ``replace`` rather than a fresh constructor: rebuilding the row field
        # by field silently dropped sentence_index the first time this was
        # written, and only the path that passes a contract showed it.
        linked.append(replace(row, obligation_ids=matches))
    return linked


def merged_plan_contract(
    contract: TaskContract, ledger: Ledger, issue_text: str = ""
) -> TaskContract:
    """The original contract plus the prompt lines nothing was tracking.

    Merged rather than kept alongside: ``evaluate_passing_observation`` walks
    ``contract.obligations``, so an obligation outside the contract can never be
    proven. Tracking a requirement that can never turn green would block the
    completion predicate permanently -- strictly worse than not tracking it.

    Returns the original object unchanged when there is nothing to add, so the
    caller can tell whether anything actually moved.
    """
    extra = ledger_only_contract(ledger, issue_text).obligations
    if not extra:
        return contract
    known = {obligation.obligation_id for obligation in contract.obligations}
    additions = tuple(item for item in extra if item.obligation_id not in known)
    if not additions:
        return contract
    obligations = contract.obligations + additions
    return TaskContract(
        role=contract.role,
        obligations=obligations,
        task_mode=contract.task_mode,
        predicates=_typed_predicates(obligations, contract.task_mode),
    )


def ledger_only_contract(ledger: Ledger, issue_text: str = "") -> TaskContract:
    """A synthetic contract over the rows no extracted obligation covers.

    These rows carry no predicate today, which is precisely how a requirement
    written verbatim in the prompt reaches submission with nothing tracking it.
    Compiling them through the normal obligation compiler gives them the same
    status, invalidation and re-verification machinery every other predicate
    already has.
    """
    obligations = tuple(
        Obligation(
            obligation_id="plan-" + row.row_id.removeprefix("req-"),
            text=row.text,
            source="persistent_plan",
            subjects=row.subjects,
        )
        for row in ledger.ledger_only
    )
    mode = _task_mode(issue_text) if issue_text else TaskMode.PATCH
    return TaskContract(
        role="code_behavior",
        obligations=obligations,
        task_mode=mode,
        predicates=_typed_predicates(obligations, mode),
    )
