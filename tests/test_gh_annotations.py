"""The workflow-command escaper, and the one place a ``::`` line is built.

REVIEW-12 MEDIUM. GitHub parses a line beginning with ``::`` off a step's
stdio as a workflow command, so every byte a CI widget interpolates into an
annotation is a command the runner obeys. ``scripts/verify_run_receipts.py``
learned that in REVIEW-11 H-1 and grew a private escaper;
``scripts/diagnose_benchmark_run.py`` prints the same kind of line out of the
same kind of model-written artifact and had none. Two copies of a security
primitive is one copy that gets forgotten, so the escaper and the command
builder live here and both modules import them.

The payload pinned below is the one REVIEW-11 reproduced end to end: three
lines, of which the runner reads two - ``::stop-commands`` silences every
later annotation in the job, and the forged ``::error title=Grader::`` states
a verdict nothing produced.
"""
from __future__ import annotations

import pytest

from scripts.gh_annotations import (
    ANNOTATION_FIELD_ALLOWANCE,
    ANNOTATION_FIELD_LIMIT,
    ANNOTATION_LINE_LIMIT,
    ANNOTATION_SEPARATOR_ALLOWANCE,
    ANNOTATION_TRUNCATION,
    MAX_ESCAPED_FIELD,
    gh_command,
    gh_command_escaped,
    gh_escape,
    gh_verbatim,
)

_INJECTION = "x\n::stop-commands::hunter2\n::error title=Grader::TASK PASSED"


def _unescape(text: str) -> str:
    """The inverse of ``gh_escape``'s message mode, applied in reverse order."""
    for char, replacement in (("\n", "%0A"), ("\r", "%0D"), ("%", "%25")):
        text = text.replace(replacement, char)
    return text


def _command_lines(rendered: str) -> list[str]:
    """Every line of ``rendered`` the Actions runner would read as a command."""
    return [line for line in rendered.split("\n") if line.startswith("::")]


def test_gh_escape_is_the_command_syntax_and_nothing_else():
    """Byte-identical to the private copy it replaces."""
    assert gh_escape("100% a\r\nb") == "100%25 a%0D%0Ab"
    # A ``title=`` value ends at a colon or a comma as well.
    assert gh_escape("a:b,c", is_property=True) == "a%3Ab%2Cc"
    # A message does not, and over-escaping it would make every check message
    # unreadable.
    assert gh_escape("a:b,c") == "a:b,c"


def test_percent_is_escaped_first_or_the_escapes_escape_themselves():
    """Order matters: ``%`` last would turn ``%0A`` into ``%250A``."""
    assert gh_escape("\n") == "%0A"
    assert gh_escape("%0A") == "%250A"


def test_the_bound_counts_source_characters_not_escapes():
    """512 of the RAW field, then escape - never 512 of percent-escapes.

    Bounding after escaping would spend the budget on ``%25`` triples and
    could cut an escape in half, which puts a bare ``%`` back in the line.
    """
    rendered = gh_escape("%" * (ANNOTATION_FIELD_LIMIT + 88))
    assert rendered == "%25" * ANNOTATION_FIELD_LIMIT + ANNOTATION_TRUNCATION
    # And nothing the escaper emits is ever truncated mid-sequence: the last
    # source character before the bound is a newline, and its escape survives
    # whole.
    edge = gh_escape("a" * (ANNOTATION_FIELD_LIMIT - 1) + "\n" + "b" * 10)
    assert edge == "a" * (ANNOTATION_FIELD_LIMIT - 1) + "%0A" + ANNOTATION_TRUNCATION
    assert "%0" not in ANNOTATION_TRUNCATION


def test_a_short_field_is_not_touched():
    assert gh_escape("plain evidence text") == "plain evidence text"
    assert gh_escape("") == ""


def test_double_escaping_is_lossless():
    """Escaping an already-escaped field still decodes back to the original.

    Two call sites may render the same field (a human stderr line and the
    annotation built from it). Neither may lose a byte of it.
    """
    for value in ("", "a", "100%", "\r\n", _INJECTION):
        once = gh_escape(value)
        twice = gh_escape(once)
        assert _unescape(once) == value
        assert _unescape(_unescape(twice)) == value


@pytest.mark.parametrize("kind", ["error", "warning", "notice"])
def test_gh_command_is_one_line_carrying_the_payload_inert(kind):
    """The reviewer's payload renders as ONE line and opens no command."""
    rendered = gh_command(kind, "Grader", _INJECTION)

    assert "\n" not in rendered and "\r" not in rendered
    assert rendered.startswith(f"::{kind} title=Grader::")
    assert _command_lines(rendered) == [rendered]
    # The bytes are still there, just inert: nothing was dropped.
    assert _unescape(rendered.split("::", 2)[2]) == _INJECTION


def test_gh_command_escapes_the_title_as_a_property():
    """A title ends at a colon or a comma, so a title carries neither raw."""
    assert gh_command("warning", "a:b,c", "m") == "::warning title=a%3Ab%2Cc::m"
    assert gh_command("error", _INJECTION, "m").count("\n") == 0


def test_gh_command_escapes_the_kind_too():
    """``kind`` is a literal at every call site today; it is still escaped.

    A field that is trusted because every caller happens to pass a literal is
    the next caller's hole.
    """
    rendered = gh_command("error\n::stop-commands", "t", "m")
    assert _command_lines(rendered) == [rendered]


def test_the_message_keeps_colons_and_commas_readable():
    """Over-escaping a message would make every annotation unreadable."""
    assert gh_command("error", "T", "a: b, c") == "::error title=T::a: b, c"


# --- REVIEW-13 MEDIUM-1: a bound belongs on a FIELD, never on the line ------
# A diagnostic line is model-written at the head and host-computed at the
# tail: ``... evidence=<what the container wrote> [VERDICT: <what the harness
# decided>]``. Bounding the COMPOSED line therefore spends the whole budget on
# the model's field and truncates the harness's verdict away - the one part of
# the line a reader needs and the only part the model cannot forge. Each field
# is bounded on its own; the line is then verified, not re-cut.

_VERDICT = " [UNEXPECTED: rust promotable, never completed]"


def _composed_line(evidence: str) -> str:
    """A capability line the way a caller must build one: field by field."""
    return (
        f"[GT][CAPABILITY][{gh_escape('DEGRADED')}] {gh_escape('lsp_promotion')} "
        f"required=True evidence={gh_escape(evidence)}{gh_escape(_VERDICT)}"
    )


def test_gh_verbatim_passes_an_already_escaped_line_through_unchanged():
    line = _composed_line("plain evidence")
    assert gh_verbatim(line) == line


def test_gh_verbatim_refuses_a_line_break_rather_than_printing_one():
    """It does not escape - it refuses. Reaching it with a raw newline means
    a caller composed a line out of fields it never escaped, which is a code
    defect, and a code defect must not be laundered into a valid-looking
    annotation."""
    for raw in ("a\nb", "a\rb", _INJECTION):
        with pytest.raises(ValueError):
            gh_verbatim(raw)


def test_gh_verbatim_refuses_a_message_no_bounded_fields_could_produce():
    """A composed line of bounded fields cannot reach the line limit. One
    that does means an unbounded field was interpolated, so it raises instead
    of flooding the job log."""
    with pytest.raises(ValueError):
        gh_verbatim("a" * (ANNOTATION_LINE_LIMIT + 1))
    assert gh_verbatim("a" * ANNOTATION_LINE_LIMIT)


def test_a_long_model_field_no_longer_truncates_the_host_verdict():
    """The regression REVIEW-13 reproduced, and its fix, side by side."""
    line = _composed_line("x" * 2_000)
    rendered = gh_command_escaped("error", "capability_not_working", line)

    # The model's field is bounded ...
    assert "x" * (ANNOTATION_FIELD_LIMIT + 1) not in rendered
    assert ANNOTATION_TRUNCATION in rendered
    # ... and the host's verdict, which comes after it, survives.
    assert "UNEXPECTED" in rendered
    assert _VERDICT.strip() in rendered
    assert rendered.count("\n") == 0

    # The same line handed to the raw-message builder loses the verdict: that
    # is the defect, kept here so the two paths cannot quietly converge.
    assert "UNEXPECTED" not in gh_command("error", "capability_not_working", line)


def test_gh_command_escaped_does_not_escape_the_message_twice():
    """Double escaping is safe but not faithful - ``%0A`` would render as
    ``%250A`` in one of the two places the same line is printed."""
    line = _composed_line("100% down\nnow")
    rendered = gh_command_escaped("warning", "T", line)

    assert "%250A" not in rendered
    assert "%2525" not in rendered
    assert rendered.endswith(line)


def test_gh_command_escaped_still_owns_its_kind_and_title():
    """Only the MESSAGE is pre-escaped; the properties are this module's."""
    assert gh_command_escaped("warning", "a:b,c", "m") == "::warning title=a%3Ab%2Cc::m"
    assert gh_command_escaped("error\n::stop-commands", "t", "m").count("\n") == 0


# --- REVIEW-14 HIGH-1: the ceiling has to be arithmetically reachable -------
# gh_escape bounds the RAW field and escapes afterwards, and escaping expands
# by up to 3x (``%`` -> ``%25``, ``\n`` -> ``%0A``, ``\r`` -> ``%0D``). So a
# bounded field is not 512 characters long, it is up to 512*3 + len(marker) =
# 1,550. The first line limit was 8*512 = 4,096 and the comment beside it said
# "a line built from bounded fields cannot reach this ceiling" - which was
# false by a factor of three: three adversarial fields already compose ~4,690
# characters, so gh_verbatim raised on real data, uncaught, and took the whole
# diagnostics render down with it.
#
# These tests pin the arithmetic itself, not a number someone typed.

_FLOOD = "%" * 3_000
_NEWLINES = "\n" * 3_000


def _compose(count: int) -> str:
    """``count`` maximally expanded fields, with separators between them."""
    fields = [gh_escape(_FLOOD if index % 2 else _NEWLINES) for index in range(count)]
    return "[GT][CAPABILITY] " + " ".join(f"f{index}={text}" for index, text in enumerate(fields))


def test_one_bounded_field_is_three_times_its_bound_plus_the_marker():
    """The 3x expansion, measured rather than assumed."""
    rendered = gh_escape(_FLOOD)

    assert rendered == "%25" * ANNOTATION_FIELD_LIMIT + ANNOTATION_TRUNCATION
    assert len(rendered) == MAX_ESCAPED_FIELD
    assert len(rendered) == ANNOTATION_FIELD_LIMIT * 3 + len(ANNOTATION_TRUNCATION)
    # Newlines and carriage returns expand by exactly as much.
    assert len(gh_escape(_NEWLINES)) == MAX_ESCAPED_FIELD
    assert len(gh_escape("\r" * 3_000)) == MAX_ESCAPED_FIELD


def test_the_line_limit_admits_the_worst_line_a_caller_can_compose():
    """The comment beside the constant must be true, not aspirational."""
    assert ANNOTATION_LINE_LIMIT == (
        MAX_ESCAPED_FIELD * ANNOTATION_FIELD_ALLOWANCE + ANNOTATION_SEPARATOR_ALLOWANCE
    )
    # The longest line in the repository is the capability line, at five
    # fields. The allowance leaves room for three more before anyone has to
    # think about this again.
    assert ANNOTATION_FIELD_ALLOWANCE >= 5


def test_eight_maximally_expanded_fields_compose_a_legal_line():
    """The case that used to raise. It is data, so it must not."""
    line = _compose(ANNOTATION_FIELD_ALLOWANCE)

    assert len(line) > 4 * ANNOTATION_FIELD_LIMIT * 3, len(line)
    assert len(line) <= ANNOTATION_LINE_LIMIT, len(line)
    assert gh_verbatim(line) == line
    assert gh_command_escaped("error", "T", line).endswith(line)


def test_a_ninth_field_still_trips_the_caller_defect_trap():
    """The raise is kept: past the allowance it IS a caller defect."""
    line = _compose(ANNOTATION_FIELD_ALLOWANCE + 1)

    assert len(line) > ANNOTATION_LINE_LIMIT, len(line)
    with pytest.raises(ValueError):
        gh_verbatim(line)
    with pytest.raises(ValueError):
        gh_command_escaped("error", "T", line)


def test_the_separator_allowance_is_what_the_real_lines_need():
    """The fixed text around the fields, measured against the real renderer."""
    assert ANNOTATION_SEPARATOR_ALLOWANCE >= len(
        "[GT][CAPABILITY][] required= evidence=" + "[GT][] task= phase= cause="
    )
