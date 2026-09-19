"""The GitHub workflow-command syntax: one escaper, one line builder.

GitHub parses a line that BEGINS with ``::`` off a step's stdio as a WORKFLOW
COMMAND, so every byte a tool in this repository interpolates into an
annotation is a command the Actions runner will obey. The fields are read off
disk and the disk is the task's: the capture receipts under
``agent/gt-state/**/output_evidence/`` and the diagnostics documents under
``<task>/agent/`` are written inside the container where the model runs
arbitrary shell, and a task id, a phase, a check message and a capability's
evidence string all come off those.

REVIEW-11 H-1 reproduced it end to end on a real trial copy. A planted
``containment_gap`` of ``x<LF>::stop-commands::hunter2<LF>::error
title=Grader::TASK PASSED`` printed three lines, of which the runner read
two: ``::stop-commands`` silences the step's own ``::error`` on rc=1, and the
forged ``::error title=Grader::`` states a verdict nothing produced.
``::add-mask::`` out of the same hole rewrites the log.

REVIEW-12 MEDIUM is why this is a module and not a private helper. The
REVIEW-11 fix lived inside scripts/verify_run_receipts.py, and
scripts/diagnose_benchmark_run.py - a second CI widget, reading a second
model-written artifact, printing the same kind of line out of the same kind
of field - had no escaping at all, in two workflows that run it on paid
attestation roots. A security primitive with two copies has one copy that
gets forgotten, so there is one; and the AST guard in
tests/test_verify_run_receipts.py runs over every module in the repository
that may print a ``::`` line, not over the one module that first grew a
defect.

https://docs.github.com/actions/reference/workflow-commands-for-github-actions
"""

from __future__ import annotations

__all__ = [
    "ANNOTATION_FIELD_ALLOWANCE",
    "ANNOTATION_FIELD_LIMIT",
    "ANNOTATION_LINE_LIMIT",
    "ANNOTATION_SEPARATOR_ALLOWANCE",
    "ANNOTATION_TRUNCATION",
    "MAX_ESCAPED_FIELD",
    "GH_MESSAGE_ESCAPES",
    "GH_PROPERTY_ESCAPES",
    "gh_command",
    "gh_command_escaped",
    "gh_escape",
    "gh_verbatim",
]

# The escaping is GitHub's own, and the ORDER matters: ``%`` first, or the
# escapes it writes are themselves escaped (``\n`` -> ``%0A`` -> ``%250A``).
GH_MESSAGE_ESCAPES = (("%", "%25"), ("\r", "%0D"), ("\n", "%0A"))
# A ``title=``/``file=`` value ends at a colon or a comma as well, so those two
# are escaped there and NOT in message text - a check message or a diagnostic
# line is mostly colons and commas, and escaping them would make every
# annotation unreadable.
GH_PROPERTY_ESCAPES = ((":", "%3A"), (",", "%2C"))

# How much of one interpolated field an annotation carries. A receipt field is
# model-writable and unbounded; without this, one planted string floods the
# job log and buries every annotation around it. The receipt FILE still
# carries the whole message - it is a file, not a log line - so nothing is
# lost, only the line is bounded.
ANNOTATION_FIELD_LIMIT = 512
# ASCII on purpose. These strings are printed to stderr by callers that run
# after their receipt is written and before they decide an exit code, so a
# UnicodeEncodeError on a console whose codepage cannot hold the character
# would escape as a traceback and rc 1 - which is a real verdict in at least
# one caller and must never mean anything else.
ANNOTATION_TRUNCATION = "...(truncated)"

# How long ONE escaped field can be, and the number REVIEW-14 HIGH-1 turned
# on. ANNOTATION_FIELD_LIMIT bounds the RAW text and the escaping runs AFTER
# it, so a bounded field is not 512 characters: every escape this module
# writes is 3 characters wide (``%`` -> ``%25``, ``\n`` -> ``%0A``, ``\r`` ->
# ``%0D``, and in property mode ``:`` -> ``%3A``, ``,`` -> ``%2C``), so a field
# of 512 ``%`` renders as 1,536 characters, plus the truncation marker.
MAX_ESCAPED_FIELD = ANNOTATION_FIELD_LIMIT * 3 + len(ANNOTATION_TRUNCATION)  # 1,550
# How many such fields one composed line may carry. The longest line in the
# repository is diagnose_benchmark_run's capability line at five; eight leaves
# room to add three before anyone has to revisit this.
ANNOTATION_FIELD_ALLOWANCE = 8
# Plus the fixed literal text between and around them - ``[GT][CAPABILITY][`` ,
# ``] required=``, ``evidence=`` and so on. Generous on purpose: it is
# host-written text, it cannot be attacked, and being stingy here is what made
# the ceiling unreachable in the first place.
ANNOTATION_SEPARATOR_ALLOWANCE = 256

# The ceiling on a COMPOSED line, and it is an assertion about the CALLER, not
# a bound applied to data. REVIEW-13 MEDIUM-1: a diagnostic line is
# model-written at the head and host-computed at the tail
# (``evidence=<container bytes> [VERDICT: <what the harness decided>]``), so
# bounding the composed line spends the entire budget on the model's field and
# truncates away the one part of the line the model cannot forge. Each field
# is bounded at ANNOTATION_FIELD_LIMIT on its own; gh_verbatim raises rather
# than silently cutting the verdict off again.
#
# REVIEW-14 HIGH-1: this was ``8 * ANNOTATION_FIELD_LIMIT`` (4,096) and the
# sentence above it claimed a line of bounded fields could not reach it. That
# was false by a factor of three - the 3x escape expansion was left out of the
# arithmetic entirely - so three container-written fields composed ~4,690
# characters, gh_verbatim raised on ORDINARY adversarial data, and the
# uncaught ValueError took out every later annotation and the whole step
# summary of a paid attestation run. The arithmetic is spelled out now, so the
# claim is checkable: 8 * 1,550 + 256 = 12,656, and
# tests/test_gh_annotations.py composes eight maximally expanded fields and a
# ninth to prove both halves.
ANNOTATION_LINE_LIMIT = (
    MAX_ESCAPED_FIELD * ANNOTATION_FIELD_ALLOWANCE + ANNOTATION_SEPARATOR_ALLOWANCE
)


def gh_escape(value: object, *, is_property: bool = False) -> str:
    """One annotation field: length-bounded, then command-syntax escaped.

    Every field interpolated into a ``::warning``/``::error``/``::notice``
    line goes through this, which a guard in tests/test_verify_run_receipts.py
    enforces over the SOURCE of every module that prints such a line rather
    than over the call sites that happen to exist: an annotation added later
    that pastes a receipt field in directly is the same defect again.

    ``is_property`` is for a ``title=``/``file=`` value.

    The bound is applied to the RAW text so the limit counts source
    characters rather than percent-escapes, and the escaping runs last so
    nothing it emits can be cut in half - a half-written ``%0A`` puts a bare
    ``%`` back into the line.
    """
    text = str(value)
    if len(text) > ANNOTATION_FIELD_LIMIT:
        text = text[:ANNOTATION_FIELD_LIMIT] + ANNOTATION_TRUNCATION
    escapes = GH_MESSAGE_ESCAPES
    if is_property:
        escapes = escapes + GH_PROPERTY_ESCAPES
    for char, replacement in escapes:
        text = text.replace(char, replacement)
    return text


def gh_verbatim(text: str) -> str:
    """A message a caller already escaped FIELD BY FIELD: verified, not re-cut.

    The counterpart to ``gh_escape`` for the message position of a composed
    line, and the answer to REVIEW-13 MEDIUM-1. Re-escaping such a line would
    double every ``%`` (the same field would read ``%0A`` on one printed line
    and ``%250A`` on the next), and re-BOUNDING it would truncate the
    host-computed verdict that follows the model's field - which is the whole
    defect.

    It refuses rather than repairs, because everything it refuses is a CODE
    defect, not a data condition. The caller's fields went through gh_escape,
    so a line break cannot survive composition, and ANNOTATION_LINE_LIMIT is
    computed from the worst case a caller CAN compose
    (ANNOTATION_FIELD_ALLOWANCE maximally expanded fields plus their
    separators) rather than guessed at. Either refusal therefore means a
    caller interpolated something raw or something unbounded, and a raw field
    printed as a valid-looking annotation is exactly what this module exists
    to prevent.

    It is still the CALLER's job not to let a refusal end a run. Failing
    closed beats emitting a line the runner obeys, but a renderer that dies on
    one row loses every row after it - see diagnose_benchmark_run._annotate,
    which catches this per row (REVIEW-14 HIGH-1).

    Only ``\r`` and ``\n`` are safety-relevant in the message position - they
    are what ends a line and lets a second command start at column zero. ``%``
    matters for fidelity, and fidelity is the caller's gh_escape to keep.
    """
    if "\r" in text or "\n" in text:
        raise ValueError(
            "pre-escaped annotation message carries a line break; "
            "escape each field with gh_escape before composing the line"
        )
    if len(text) > ANNOTATION_LINE_LIMIT:
        raise ValueError(
            f"pre-escaped annotation message exceeds {ANNOTATION_LINE_LIMIT} "
            "characters; a line of gh_escape'd fields cannot, so a field was "
            "interpolated unbounded"
        )
    return text


def gh_command(kind: str, title: str, message: str) -> str:
    """One complete workflow-command line from RAW text, every field escaped.

    This and ``gh_command_escaped`` are the only places in the repository that
    own a ``::`` literal followed by interpolated text. A caller that builds
    its own line has to remember three escapes, two escape MODES and an order;
    a caller that calls one of these has to remember nothing, and the guard in
    tests/test_verify_run_receipts.py can then insist that the caller owns no
    ``::`` literal at all.

    Use this when the whole message is one field, or is short and
    host-computed. Use ``gh_command_escaped`` when the message is composed
    from several fields and one of them is model-written: this one bounds the
    COMPOSED message, which cuts off whatever comes after a long field.

    ``kind`` is a literal (``error``, ``warning``, ``notice``) at every call
    site today and is escaped anyway: a field trusted because every current
    caller passes a constant is the next caller's hole. It is escaped in
    property mode, so a ``kind`` carrying a colon cannot end the command name
    early and start a property.

    The result is guaranteed to be a SINGLE line - no ``\r`` and no ``\n``
    survive gh_escape - so a planted field can neither open a second command
    nor put one at column zero.
    """
    return (
        f"::{gh_escape(kind, is_property=True)}"
        f" title={gh_escape(title, is_property=True)}"
        f"::{gh_escape(message)}"
    )


def gh_command_escaped(kind: str, title: str, message: str) -> str:
    """The same line, for a ``message`` the caller escaped field by field.

    ``kind`` and ``title`` are still this module's to escape - a caller has no
    business knowing that a property value ends at a colon. Only the message
    is the caller's, and it is verified by ``gh_verbatim`` rather than
    re-escaped, so the annotation carries the caller's own human-readable line
    byte for byte and nothing after a long field is cut away.
    """
    return (
        f"::{gh_escape(kind, is_property=True)}"
        f" title={gh_escape(title, is_property=True)}"
        f"::{gh_verbatim(message)}"
    )
