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


def test_a_signature_whose_parameter_order_differs_is_shown_beside_the_task_s():
    # true-myth GT-on: the task names tap(task, fn); the change defined tap(fn, task).
    # Every word of the signature appears in the change, so the literal check passed.
    issue = "Add `tap(task, fn)` which calls fn with the resolved value and returns the task."
    added = "export function tap<T>(fn: (value: T) => void, task: Task<T>): Task<T> {\n  return task;\n}"
    text = build_review(issue, added).render()
    assert "[task: tap(task, fn); yours: tap(fn, task)]" in text
    same = build_review(issue, "export function tap<T>(task: Task<T>, fn: (v: T) => void) {}").render()
    assert "yours:" not in same
    python = build_review("Provide `lag(column, offset=None)`.", "def lag(column, offset=None):\n    pass")
    assert "yours:" not in python.render()


def test_a_requirement_quoting_code_in_backticks_is_kept():
    rows = requirement_lines("Add `tap(task, fn)` to `task`; it also has a curried form `tap(fn)` "
                             "returning `(task) => result`.")
    assert len(rows) == 1 and rows[0].startswith("Add `tap(task, fn)`")
    assert requirement_lines("const handler = (task) => result;") == []  # a bare code line still is not


def test_limiting_sentences_are_marked_as_constraints():
    # kysely GT-on added `Expression<any>` where the task said "(not reference expressions)".
    issue = ("Add ntile, nthValue, lag and lead helpers. Their numeric arguments accept number | bigint "
             "(not reference expressions). The helpers compile to standard SQL.")
    rows = build_review(issue, "export function ntile(n: number | Expression<any>) {}").render().splitlines()
    constraint = next(row for row in rows if "not reference expressions" in row)
    assert "[constraint]" in constraint
    assert not any("[constraint]" in row for row in rows if "compile to standard SQL" in row)


def test_an_oversized_review_drops_plain_rows_first_and_says_which():
    plain = [f"The widget number {i} renders a label beside its icon in the toolbar area." for i in range(200)]
    issue = " ".join(plain[:100] + ["The value must never exceed `MAX_DEPTH`."] + plain[100:])
    text = build_review(issue, "x = 1").render()
    assert "must never exceed `MAX_DEPTH`" in text  # flagged + constraint rows survive the cap
    assert "not shown (plain descriptions" in text
    assert len(text.encode("utf-8")) <= 12_500


def test_issue_template_placeholders_are_not_requirements():
    rows = requirement_lines("### Description\nAdd a get_value function for FSMContext that takes value by key\n"
                             "### Additional information\n_No response_\nN/A\n")
    assert rows == ["Add a get_value function for FSMContext that takes value by key"]

