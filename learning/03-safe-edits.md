# Phase 03 — Making Edits Safe (and Measuring Them)

**Code:** `agent/editor.py`, `agent/graph.py` (`generate_node`, prompts),
`evals/`

## The one-paragraph explanation

In phase 02 the model rewrote the *whole file* for every edit. Small models
copy long files imperfectly — in a real run one silently deleted the file's
working imports. This phase changes **how edits are made** and adds **guards**
that check every edit *before* it touches the disk — and then **measures**
whether each change actually helps.

## How an edit flows

```
model reply
   ├─ SEARCH/REPLACE blocks? ─► apply (exact → indentation-tolerant → ≥85% similar & unique)
   ├─ else a ``` code block? ─► treat as the whole new file
   └─ else ────────────────────► "use the format" problem
   ▼
GUARDS (fail → nothing written, model retries with the reason)
   ├─ markers leaked?  <<<<<<< / ======= / >>>>>>> in the code
   ├─ deletion guard   an import removed, or > 3 existing lines removed
   └─ duplication      > 3 existing lines now appear twice
   ▼
write ─► verify ─► lookup on failure
```

SEARCH/REPLACE (the approach Aider and Claude Code use):

```
<<<<<<< SEARCH
import 'dart:convert';
=======
import 'dart:convert';
import 'app_logger.dart';
>>>>>>> REPLACE
```

Only lines named in SEARCH can change; everything else is safe by construction.

## Lessons from real runs

| What happened | Fix |
|---|---|
| Model deleted working imports in a whole-file rewrite | SEARCH/REPLACE + deletion guard |
| Model pasted the whole class *inside* a method | duplication guard |
| `=======` ended up in the code | marker check + a more tolerant block parser |
| `void f()` matched *inside* `  void f()` → double indentation | exact matches must start at a line start |
| A long hint pasted another file's code → model edited *that* file's lines | facts cut to one sentence |
| Retry attempts stacked on broken attempts → method added twice | every attempt starts from the original file |
| Same wrong answer 4× at temperature 0 | temperature 0 for attempt 1, 0.4 for retries |
| Buried in a 5,000-token prompt, the model ignored the error | short, focused repair prompt |

**Validate outputs, don't just constrain them:** no 7B model follows a format
100% of the time; accept several formats and check the *result*.

## Measure, don't eyeball

Judging a change by one or two runs fooled me several times. `evals/` runs
fixed tasks several times and gives a score; a run passes only if the analyzer
passes *and* regex checks on the result hold.

```bash
python -m agent.cli index examples/demo_app
python -m evals.run_eval --runs 2
python -m evals.run_eval --mode add     # compare strategies
```

Measured on a real Flutter project (5 tasks × 2 runs, `qwen2.5-coder:7b`):

| Edit mode | Score | Time per run |
|---|---|---|
| `search_replace` | **7/10** | 100–240 s |
| `add` (model writes only new code; program inserts it) | 6/10 | **15–80 s** |

A real trade-off — visible only because it was measured.

## Debugging

```bash
AGENT_DEBUG=1 python -m agent.cli do "..." --file some/file
```
Prints every raw model reply. Most fixes above came from reading these.

## Check your understanding

- Why can't SEARCH/REPLACE delete code that is not in a SEARCH block?
- Why do the guards run *before* write, and the analyzer *after*?
- The deletion guard compares sets of lines. What deletion could it miss?
- Why is a score over 10 runs more trustworthy than one good run?
