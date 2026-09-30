# Phase 04 — Coding Standards: Check, Review, Fix

**Code:** `agent/standards.py`, `standards/default.md`,
`agent/cli.py` (`check`, `fix`), `/review` in `agent/server.py`

## The one-paragraph explanation

A team writes its coding standard as plain text. The agent checks any file
against it and reports violations with line numbers, then — on request —
fixes them through the phase 02/03 agent loop. Works for any language: rules
are text and the linter is auto-detected.

## Three sources, from most to least reliable

| Source | How | Strength | Weakness |
|---|---|---|---|
| Linter | the project's analyzer | exact, official | knows only language rules |
| Regex rules | rule has a `pattern:` line | instant, never invents | only textual patterns |
| LLM rules | model reads the numbered file, answers JSON | judges meaning ("services must not use UI code") | slower, can be wrong |

Rule of thumb: **if a rule can be a regex, make it a regex.**

```
## no-print: Do not use print() for logging; use the project's logger.
pattern: ^\s*print\(

## service-no-ui: Service classes must not use UI code (BuildContext, Navigator, dialogs).
```

## Free-form code review

Review mode takes *any* Markdown guideline file (e.g. the demo app's
`coding_standard.md`) and returns findings: line, rule, problem, suggestion.

The first version returned **26 findings in 2 minutes** — many repeated, some
invented (a "print()" on a line without one). Two changes fixed that:

1. **Evidence:** each finding must *quote* the code at its line; if the quote
   isn't really there (±2 lines), the finding is dropped.
2. **No repeats:** same rule + same problem → one finding; the prompt asks to
   report each problem once.

Result: **4 findings in 31 s**, 2 of them real and 2 wrong (the model believed
calling `.add()` on a `final` list is a reassignment). That's why review only
*suggests*; "Fix these" goes through the normal approve/reject flow.

## Try it

```bash
python -m agent.cli index examples/demo_app          # once
python -m agent.cli check lib/services/auth_service.dart --no-llm
```
(File paths are relative to the indexed project.)

## Check your understanding

- Why validate the LLM's JSON (rule ids, line numbers, quotes) instead of
  trusting it?
- Why does a *fix* run turn off the deletion guard?
- Which rules in `demo_app/coding_standard.md` could be regex rules?
