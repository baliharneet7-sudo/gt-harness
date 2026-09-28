"""Pre-submit requirement review (gt_engine.submit_review) and its one-shot hold."""
from __future__ import annotations

from types import SimpleNamespace

from gt_engine.submit_review import build_review, literals_of, requirement_lines

CLIFFY_LIKE = (
    "Please solve this issue: The Command class gains a config method accepting ConfigOptions "
    "with fields name (required), searchPaths, formats, mergeConfigs, and parser. When searchPaths "
    "is not provided, the current directory is used. For each search path, the framework looks for "
    "name.json then .namerc. Malformed config files throw ConfigParseError.\n\n"
    "IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.\n"
    "You can execute bash commands and edit files to implement the necessary changes.\n"
    "```ts\nconst cmd = new Command().config({ name: \"app\" });\n```\n"
)

BANDIT_LIKE = (
    "Taint propagates through concatenation and calls. Resolve sinks through import aliases. "
    "Parameterized queries (taint in params, not query), int(), shlex.quote, os.path.basename, "
    "flask.escape, and markupsafe.escape are safe.\n"
    "- `--cache-summary` prints \"Cached files: N\".\n"
)


def test_every_requirement_sentence_is_its_own_row_and_process_text_is_dropped():
    rows = requirement_lines(CLIFFY_LIKE)
    assert "For each search path, the framework looks for name.json then .namerc." in rows
    assert any(row.startswith("The Command class gains a config method") for row in rows)
    assert not any("new branch" in row or "bash commands" in row for row in rows)
    assert not any("new Command()" in row for row in rows)  # fenced code is not a requirement


def test_safe_lists_the_plan_ledger_dropped_are_kept():
    rows = requirement_lines(BANDIT_LIKE)
    assert any("shlex.quote" in row and "are safe" in row for row in rows)
    assert any(row.startswith("`--cache-summary` prints") for row in rows)


def test_literals_cover_bare_dot_names_flags_quotes_and_code_identifiers():
    assert ".namerc" in literals_of("the framework looks for name.json then .namerc.")
    assert "--cache-summary" in literals_of("`--cache-summary` prints \"Cached files: N\".")
    assert "Cached files: N" in literals_of("--cache-summary prints \"Cached files: N\".")
    assert "os.path.basename" in literals_of("int(), shlex.quote, os.path.basename are safe")
    assert literals_of("evict deterministically by oldest creation order") == ()


def test_a_literal_missing_from_the_changes_is_flagged_and_templates_match_by_words():
    wrong = "const file = `${name}${format}`;"  # cliffy GT-on: never looks for .namerc
    review = build_review(CLIFFY_LIKE, wrong)
    namerc = next(row for row in review.rows if ".namerc" in row.text)
    assert ".namerc" in namerc.missing
    template = build_review("`--cache-summary` prints \"Cached files: N\".",
                            'parser.add_argument("--cache-summary")\nprint(f"Cached files: {n}")')
    assert template.flagged == []


def test_render_lists_every_requirement_once_and_marks_missing_literals():
    text = build_review(CLIFFY_LIKE, "const file = `${name}${format}`;").render()
    assert text.startswith("[GT] before you submit:")
    assert "this review appears once" in text
    assert "looks for name.json then .namerc.   [not in your changes: .namerc" in text
    assert "new branch" not in text


def _gate(monkeypatch, review_text):
    from gt_engine import miniswe_runtime

    monkeypatch.setattr(miniswe_runtime, "is_attached", lambda: True)
    events = []
    attached = SimpleNamespace(calls=0)

    def submit_review_once():
        attached.calls += 1
        return review_text if attached.calls == 1 else ""

    attached.submit_review_once = submit_review_once
    adapter = SimpleNamespace(attached_delivery=attached, pending_directives=[],
                              store=SimpleNamespace(append=lambda event, **row: events.append(event)))
    session = SimpleNamespace(engine=adapter, disabled=False)
    return miniswe_runtime, session, adapter, events


def test_the_first_submit_is_held_once_with_the_review_and_the_second_goes_through(monkeypatch):
    runtime, session, adapter, events = _gate(monkeypatch, "[GT] before you submit: ...")
    assert runtime._run_submit_gate(session, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                                    pre_execution=True) is False
    # Not a directive: attached sessions are SHADOW and drop directives. The
    # review rides the held submit's own observation.
    assert adapter.pending_directives == []
    assert adapter.attached_submit_review == "[GT] before you submit: ..."
    assert runtime._run_submit_gate(session, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                                    pre_execution=True) is True
    assert events == ["submit_review_held", "submit_gate_bypassed"]


def test_no_review_means_no_hold(monkeypatch):
    runtime, session, adapter, events = _gate(monkeypatch, "")
    assert runtime._run_submit_gate(session, "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
                                    pre_execution=True) is True
    assert adapter.pending_directives == []


def test_issue_template_placeholders_are_not_requirements():
    rows = requirement_lines("### Description\nAdd a get_value function for FSMContext that takes value by key\n"
                             "### Additional information\n_No response_\nN/A\n")
    assert rows == ["Add a get_value function for FSMContext that takes value by key"]

