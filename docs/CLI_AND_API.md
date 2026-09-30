# CLI, HTTP API, Configuration, Evaluations

Everything the VS Code extension does is also available from the terminal and
over HTTP. Run commands from the repo root with the venv active
(`source venv/bin/activate`).

## Command line — `python -m agent.cli`

```bash
python -m agent.cli index examples/demo_app                 # build the index
python -m agent.cli ask "How does login work?"               # RAG answer
python -m agent.cli ask "How does login work?" --no-rerank   # compare without stage 2
python -m agent.cli do "Add a toJson() method" --file lib/models/user.dart
python -m agent.cli do "..." --file x.dart --verify "dart analyze {file}" --mode add
python -m agent.cli check lib/services/auth_service.dart --no-llm   # fast: linter + regex rules
python -m agent.cli fix lib/services/auth_service.dart             # check + agent fix + y/N
```

`do` and `fix` show the diff and ask `Keep this change? [y/N]`; anything but
`y` restores the file. The CLI refuses files with uncommitted changes.
The CLI uses `agent_index.json` in the repo root (the server keeps one index
per project in `indexes/`).

## HTTP API — `uvicorn agent.server:app --port 8765`

Interactive docs: http://localhost:8765/docs

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | Ollama status, model, current project, indexing progress |
| POST | `/project` | `{project_path}` | switch project; starts background indexing if new |
| POST | `/index` | `{project_path}` | re-index in the background |
| GET | `/index/status` | — | `{state, done, total}` |
| POST | `/ask` | `{question, files?}` | `answer`, `sources` |
| POST | `/do` | `{task, file, context?, mode?}` | proposal: `diff`, `new_content`, `passed`, `attempts`, `todos` |
| POST | `/review` | `{file, context?, focus?}` | `findings` (line, rule, problem, suggestion) |
| POST | `/check` | `{file, use_llm}` | `violations` |
| POST | `/fix` | `{file, use_llm}` | `violations` + proposal |
| POST | `/cancel` | — | stop the running agent after its current step |
| GET | `/models` | — | installed chat models |
| POST | `/model` | `{name}` | switch model |
| POST | `/pull` | `{name}` | download a model with Ollama |

`file` paths are relative to the project. `/do` and `/fix` never leave a file
changed — the client applies `new_content` if the user accepts.

## Configuration — `agent/config.py`

| Setting | Default | Meaning |
|---|---|---|
| `CHAT_MODEL` | `qwen2.5-coder:7b` | model for answers and edits (the chat dropdown overrides it) |
| `EMBED_MODEL` | `nomic-embed-text` | model for the index |
| `NUM_CTX` | 16384 | context window (tokens); lower it if the Mac swaps |
| `TEMPERATURE` | 0 | 0 = reproducible |
| `MAX_ATTEMPTS` | 5 | agent retries |
| `EDIT_MODE` | `search_replace` | or `add` (faster, new code only) / `auto` |
| `CANDIDATES` / `TOP_K` | 15 / 4 | retrieval stage 1 / stage 2 sizes |

Environment variables:

| Variable | Use |
|---|---|
| `AGENT_TOOL_PATHS` | extra folders for analyzers not on `PATH`, e.g. `~/flutter/bin:~/go/bin` |
| `AGENT_DEBUG=1` | print the model's raw replies (best way to understand a failure) |

**Add a tech stack's checker:** one row in `VERIFY_RULES` in `agent/tools.py`
(marker file, tool, command).

**Coding standards:** `standards/default.md`, or `<project>/.agent/standards.md`
for per-project rules. In the chat, any Markdown file added with **@ Context**
works for Review.

## Evaluations — `evals/`

A 7B model's output varies from run to run, so changes are judged by a
**score**, not by one lucky run.

```bash
python -m agent.cli index examples/demo_app      # evals run on the demo app
python -m evals.run_eval                          # 5 tasks × 2 runs
python -m evals.run_eval --runs 3 --mode add      # compare edit strategies
python -m evals.run_eval --only add-logout
```

A run passes when the analyzer passes **and** the task's `must_contain` /
`must_not_contain` regexes hold. Results (score, diffs, logs) are saved in
`evals/results/`. Tasks live in `evals/tasks.json`.

## VS Code extension development

```bash
cd vscode-extension
npm install
npm run compile
npx vsce package --allow-missing-repository --skip-license   # -> .vsix
```

Or open `vscode-extension/` in VS Code and press **F5** to run it in a
development window.
