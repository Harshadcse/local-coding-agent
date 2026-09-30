# Learning Path: Build an Offline Coding Agent Step by Step

This folder shows **how the project was built**, one phase at a time — from a
single LLM call to a VS Code extension. The main code (`agent/`,
`vscode-extension/`) is the finished result; this folder is the path to it.

Each phase: the concept in one paragraph, the design decisions, what went
wrong along the way, and questions to check your understanding.

| # | Phase | You learn |
|---|---|---|
| [00](00-basics/) | **Basics** — scripts: one LLM call, embeddings, a tiny RAG demo, a first indexer | What an LLM call, an embedding and RAG are |
| [01](01-retrieval.md) | **Retrieval** — index a project, two-stage search | Why naive RAG fails and how real systems fix it |
| [02](02-agent-loop.md) | **Agent loop** — tools + LangGraph, verify and retry | What makes something an *agent* instead of a chatbot |
| [03](03-safe-edits.md) | **Safe edits** — SEARCH/REPLACE, guards, measuring with evals | Why you validate model output instead of trusting it |
| [04](04-coding-standards.md) | **Coding standards** — linter + regex + LLM rules, code review | How to get reliable, structured results from an LLM |
| [05](05-server-and-extension.md) | **Server + VS Code extension** — FastAPI, chat UI, proposals | How a Copilot-style editor experience is built |

**Prerequisites:** Python basics, [Ollama](https://ollama.com) installed with
`nomic-embed-text` and a chat model (`qwen2.5-coder:7b`). Run `./setup.sh` in
the repo root once.

For the finished system explained as one flow, see
[docs/HOW_IT_WORKS.md](../docs/HOW_IT_WORKS.md). For the lessons in short
form, see [docs/LESSONS.md](../docs/LESSONS.md).

> The phase guides describe each step *as it was built*. Later phases changed
> earlier code (for example, whole-file edits were replaced by SEARCH/REPLACE
> in phase 03), so the current code is the source of truth.
