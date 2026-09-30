# Phase 01 — A Proper Retrieval Pipeline

**Code:** `agent/config.py`, `agent/llm.py`, `agent/indexer.py`,
`agent/retriever.py`, `agent/cli.py` (`index`, `ask`)

## The one-paragraph explanation

Search quality is everything in RAG: if the wrong code is retrieved, even a
perfect model gives a wrong answer. The naive version from phase 00 was fooled
by keyword overlap — a translation JSON containing `login_email`,
`login_password` outranked the real login service. This phase turns the
scripts into a package and fixes retrieval.

## The flow

```
INDEX (once per project)                ASK (every question)
project folder                          "how does login work?"
  │ find_source_files()                    │ embed(kind="query")
  ▼                                        ▼
files ─ chunk_text() ─► chunks          Stage 1: cosine similarity vs all chunks
  │ "File: path\n" + chunk                 │ (data files get a small penalty) → top 15
  ▼ embed(kind="document")                 ▼
vectors ─► index JSON                   Stage 2: LLM scores each 0–10 (rerank) → top 4
                                           ▼
                                        prompt = rules + 4 chunks + question → answer with file paths
```

## Design decisions (and why)

1. **File path embedded with each chunk.** `services/auth_service.dart` says a
   lot about what the code is for.
2. **Query/document prefixes.** `nomic-embed-text` was trained with
   `search_query:` / `search_document:`; using them improves matching.
3. **Code vs data tagging.** `.json/.yaml/.md/...` get a small penalty for code
   questions. Still language-agnostic: tag by "is this data?", not by language.
4. **Two-stage retrieval.** Vector search is fast but shallow; the LLM *reads*
   15 candidates and picks the best 4. The same pattern production search uses.
5. **Smaller chunks (3,000 chars) + line numbers.** More precise hits; the
   agent will need line numbers to edit.
6. **Long lines truncated.** Minified files no longer break embedding.
7. **System prompt:** cite file paths, say "I don't know" instead of inventing.
8. **Modules, one job each.** `llm.py` is the *only* file that talks to Ollama
   — swap the model provider by changing one file.

## Try it

```bash
python -m agent.cli index examples/demo_app
python -m agent.cli ask "how does login work in this app?"
python -m agent.cli ask "how does login work in this app?" --no-rerank   # compare
```

## Check your understanding

- Why embed the question with a different prefix than the code?
- Why rerank 15 chunks and not all of them? (One LLM call vs hundreds.)
- What would break if `DATA_FILE_PENALTY` were 0?
- Why keep line numbers in the index?
