# How It Works

This document walks through the system in the order data flows through it.
Each step names the file to read. Read them in this order and you can explain
— or rebuild — the whole agent.

```
 1. Index        2. Retrieve        3. Agent loop                       4. Review          5. Server        6. Extension
 project files → relevant chunks → retrieve → plan → generate → write  → standards /    → FastAPI       → VS Code chat
 → embeddings                       → verify → (lookup → retry)          code review      (localhost)     Ask/Edit/Review
```

---

## 1. Indexing — `agent/indexer.py`

**Goal:** make the project searchable by *meaning*, not just keywords.

1. `find_source_files()` walks the project and skips what is never useful:
   `.git`, `node_modules`, `build`, binaries, huge generated files. It decides by
   *what is junk*, not *what language it is* — so it works for any tech stack.
2. `chunk_text()` splits each file into ~3,000-character chunks on line
   boundaries and keeps line numbers (the agent later needs them to edit).
3. Each chunk is **embedded**: turned into a vector (a list of numbers) by the
   `nomic-embed-text` model. Texts with similar meaning get similar vectors.
   The file path is put in front of each chunk before embedding
   (`File: lib/services/auth_service.dart`) — a path is a strong hint about
   what code is *for*.
4. Files are tagged `code` or `data` (`.json`, `.yaml`, `.md`, …) so data files
   can be ranked lower for code questions.
5. The index is saved as JSON: one per project in `indexes/`.

The server indexes a new project **in the background**; until it finishes,
everything still works, just without project-wide search.

## 2. Retrieval (RAG) — `agent/retriever.py`

**RAG** = Retrieval-Augmented Generation: before asking the LLM, find the
relevant code and put it in the prompt, so the model answers from *your* code
instead of guessing.

Two stages, the standard pattern in real search systems:

| Stage | How | Why |
|---|---|---|
| 1. Vector search | cosine similarity between the question's vector and every chunk; data files get a small penalty; keep the top 15 | fast, but fooled by keyword overlap (e.g. a translation file full of `login_*` keys beats the real login code) |
| 2. LLM rerank | the chat model reads the 15 candidates and scores each 0–10; keep the top 4 | slower, but judges real relevance |

`nomic-embed-text` also expects prefixes: `search_query:` for questions,
`search_document:` for code — using them measurably improves matching.

## 3. The agent loop — `agent/graph.py` (LangGraph)

A chatbot only *talks*. An **agent** *acts*: it uses tools, looks at the
result, and decides what to do next. LangGraph expresses that as a graph:

```
 retrieve ──► plan ──► generate ──► write ──► verify ──► END (passed)
                         ▲   │                  │
                         │   └ edit rejected ───┤ (retry)
                         └──── lookup ◄─────────┘ (checker failed)
```

LangGraph in three ideas:

- **State** (`AgentState`): one dictionary every step reads and updates.
- **Nodes**: plain Python functions (`retrieve_node`, `generate_node`, …).
- **Edges**: which node runs next. A *conditional* edge (`after_verify`)
  looks at the state and decides — that decision is what makes it an agent.

The steps:

| Node | Does |
|---|---|
| `retrieve` | step 2, with the target file name added to the query |
| `plan` | picks which file to edit (skipped when a file is given — the extension always gives one) |
| `generate` | asks the model for the change (see step 3b) |
| `write` | saves it, because the checker needs a real file |
| `verify` | runs the project's analyzer, auto-detected in `tools.py` (`pubspec.yaml` → `dart analyze`, `go.mod` → `go vet`, …) |
| `lookup` | after a failure: finds the names in the error message (`'logoutUrl'`), searches the index for their definitions, and tells the model "X is defined in file Y — import it" or "X does not exist — don't use it" |

**Why `lookup` matters:** feeding errors back alone is not enough — a small
model repeats the same invented name. New *facts* are what let it fix things.

Other important details:

- The **first prompt** contains the task, related code, the file, any context
  files (e.g. the coding standard), and the checker errors the file *already*
  has (so "fix error" works).
- **Every attempt starts from the original file**, and retries use a short,
  focused prompt: "you changed this, the checker says that, fix it".
- A missing checker tool (exit code 127) stops the loop instead of retrying.
- Temperature is 0 for attempt 1 (reproducible) and 0.4 for retries (so a
  retry can't repeat the exact same wrong answer).
- Stop/cancel is checked between steps; the original file is always restored.

### 3b. Safe edits — `agent/editor.py`

Asking a small model to rewrite a whole file is risky: it silently drops lines.
So the model returns only **SEARCH/REPLACE blocks**:

```
<<<<<<< SEARCH
import 'dart:convert';
=======
import 'dart:convert';
import 'app_logger.dart';
>>>>>>> REPLACE
```

Only lines named in a SEARCH block can change. Matching is exact, then
indentation-tolerant, then near-identical (≥ 85% similar, unique) — models
often copy a line slightly wrong. Then **guards** check the result before
anything is written:

| Guard | Rejects |
|---|---|
| deletion | removing any import, or more than 3 existing lines (off for "fix" tasks) |
| duplication | existing code pasted a second time |
| markers | leftover `<<<<<<<` / `=======` in the code |

A rejected edit goes back to the model with the exact reason.
(`add` mode is an alternative: the model returns only new code + imports and
the program inserts them — faster, see [LESSONS.md](LESSONS.md).)

## 4. Coding standards and review — `agent/standards.py`

Two tools:

**Checklist check** (`check`/`fix`, rules in `standards/default.md`):

| Source | Strength |
|---|---|
| Linter (the project's analyzer) | exact |
| Regex rules (`pattern:` line) | instant, never invents |
| LLM rules (no pattern) | judges meaning, can be wrong — answers are validated |

**Code review** (`review_file`, used by Review mode): the model reads the
line-numbered file and your guideline files (any Markdown) and returns
findings as JSON. Each finding must **quote the code at that line** — if the
quote isn't really there, the finding is dropped as invented. Repeats are
merged. "Fix these" turns findings into an Edit task.

## 5. Server — `agent/server.py`

The extension is TypeScript and can't import Python, so the agent runs as a
local HTTP server (FastAPI, `localhost:8765`). Key design: **`/do` returns a
proposal, not an edit** — the server runs the agent, restores the original
file, and returns the new content + diff. The editor writes the file only
when the user accepts. One agent run at a time; `/cancel` stops it after the
current step. Endpoints are listed in [CLI_AND_API.md](CLI_AND_API.md).

## 6. VS Code extension — `vscode-extension/src/`

| File | Job |
|---|---|
| `api.ts` | the only file that calls the server; finds the project root of a file |
| `chatView.ts` | the chat: history, Ask/Edit/Review, @ Context, proposal & review cards, model picker |
| `proposals.ts` | shows a proposal in VS Code's diff editor, applies it as an undoable edit |
| `server.ts` | starts/stops the Python server, status bar item |
| `extension.ts` | registers everything; right-click commands; problem squiggles |

The chat is a **webview** (a small web page). It can't call the extension
directly, so the two exchange messages. The extension owns the chat history
(saved per workspace), so the conversation survives closing the panel.

## A request, end to end

"Edit: add a logout() method" with `auth_service.dart` open:

1. Extension finds the project root (`pubspec.yaml`), tells the server (`/project`).
2. Extension sends `/do` with the task, the file, and the @ Context files.
3. Server runs the analyzer on the current file → existing errors (none).
4. Graph: retrieve related code → generate SEARCH/REPLACE → guards → write →
   `dart analyze` → passed.
5. Server restores the original file and returns the proposal.
6. Chat shows the proposal card; user clicks **Accept** → the extension writes
   the file as an undoable edit.
