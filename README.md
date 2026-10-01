# Local Coding Agent

**A GitHub Copilot / Claude-style coding assistant that runs 100% offline** —
chat about your codebase, let an agent edit files (you approve every change),
and review code against your team's own coding standard. Built with a local
LLM ([Ollama](https://ollama.com)), retrieval-augmented generation (RAG),
[LangGraph](https://github.com/langchain-ai/langgraph) and a VS Code extension.

No cloud, no API keys, no code leaves your machine.

> Built as a personal learning project to explore local LLMs, RAG and AI agents.

```
┌──────────── VS Code ────────────┐        ┌──────── Python agent (FastAPI) ────────┐      ┌─ Ollama ─┐
│ Chat panel: Ask · Edit · Review │  HTTP  │ RAG: index → search → rerank           │      │ chat LLM │
│ @ Context files · model picker  │◄──────►│ Agent loop (LangGraph): plan → edit →  │◄────►│ embedder │
│ Proposal cards: Accept/Reject   │ :8765  │   verify (analyzer) → lookup → retry   │      └──────────┘
│ Squiggles for standard issues   │        │ Coding-standard checks (linter/regex/LLM)│
└─────────────────────────────────┘        └─────────────────────────────────────────┘
```

## Features

| | |
|---|---|
| **Ask** | Questions about the project. Answers cite the source files (click to jump). The open file is always included as context. |
| **Edit** | Describe a change; the agent edits the open file, runs the project's analyzer, and self-corrects on errors. The result is a **proposal card** in the chat — diff, checker result, TODOs — with **Accept / Reject**. Nothing is written until you accept (and Cmd+Z undoes it). |
| **Review** | Reviews the open file against files you add with **@ Context** (e.g. `coding_standard.md`) and lists findings with line numbers. **Fix these** turns them into an Edit. |
| **Any tech stack** | Nothing is tied to one language: the indexer, the edit logic and the rules are language-agnostic; the analyzer is auto-detected (`dart analyze`, `tsc`, `go vet`, `cargo check`, `py_compile`, …). |
| **Any Ollama model** | Pick installed models from a dropdown, or install new ones from the chat. |
| **Safe by design** | Edits are proposals; guards reject edits that delete or duplicate existing code; the file is restored if anything fails; paths can't escape the project. |

## Quick start (about 10 minutes)

**Needs:** macOS or Linux, Python 3.11+, Node.js 18+, [Ollama](https://ollama.com/download), VS Code.
~6 GB free RAM for the default model (`qwen2.5-coder:7b`). Flutter/Dart only for the demo app's analyzer.

```bash
git clone https://github.com/Harshadcse/local-coding-agent.git
cd local-coding-agent
./setup.sh            # venv + Python deps, Ollama models, builds the VS Code extension
```

Then:

1. In VS Code: **Extensions → `…` → Install from VSIX…** → `vscode-extension/local-coding-agent-*.vsix`
   (or download the `.vsix` from the [Releases](../../releases) page).
2. Open `examples/demo_app` (or your own project) in VS Code.
3. Click the **robot icon** in the Activity Bar → **Start** (first time: select this repo's folder).
4. Open `lib/services/auth_service.dart`, choose **Review**, click **@ Context** → `coding_standard.md`, **Send**.

The first time a project is used it is indexed in the background (progress in
the chat header); Ask/Edit/Review work immediately.

## Documentation

| Doc | For |
|---|---|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | The full flow, step by step: indexing, RAG, the agent loop, safe edits, standards, server, extension |
| [docs/DEMO.md](docs/DEMO.md) | A 10-minute demo script for presenting to a team |
| [docs/CLI_AND_API.md](docs/CLI_AND_API.md) | Command-line use, HTTP API, configuration, evaluations |
| [docs/LESSONS.md](docs/LESSONS.md) | What I learned building an agent on a small local model |
| [learning/](learning/) | **Learning path:** how it was built, phase by phase — from a single LLM call to the VS Code extension, with questions to check your understanding |
| [examples/demo_app](examples/demo_app) | Sample Flutter app with planted coding-standard issues |

## Project layout

```
agent/              Python agent
  indexer.py          walk project → chunk → embed → index
  retriever.py        vector search + LLM rerank
  graph.py            LangGraph agent loop (retrieve → plan → generate → write → verify → lookup)
  editor.py           SEARCH/REPLACE edits + safety guards
  tools.py            file access (sandboxed to the project), commands, analyzer detection
  standards.py        coding-standard checks and code review
  server.py           FastAPI server used by the extension
  cli.py              command line
  llm.py, config.py   Ollama calls, all settings
vscode-extension/   TypeScript extension (chat, proposals, server control)
standards/          default coding-standard rules
evals/              fixed tasks + runner to measure the agent
examples/demo_app/  sample project for demos
learning/           step-by-step learning path (phase guides + first scripts)
```

## Honest limits

A 7B model running on a laptop is far weaker than the models behind Copilot or
Claude. It does well on clear, specific tasks ("add a toJson() method") and
struggles with vague ones ("add logout" when no logout API exists). Review
findings can include false positives. That is why every edit is a proposal you
approve, and why the analyzer checks every change. A bigger model
(`qwen2.5-coder:14b`) helps if your machine has the memory.

## License

[MIT](LICENSE)
