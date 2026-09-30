# Phase 00 — Basics

Four small scripts, each adding one idea. Run them from the repo root with the
venv active (`source venv/bin/activate`) and Ollama running.

| Script | Idea | Run |
|---|---|---|
| `ask.py` | **An LLM call** — send a message to Ollama's `/api/chat`, print the reply | `python learning/00-basics/ask.py` |
| `similarity_test.py` | **Embeddings** — turn sentences into vectors; *cosine similarity* shows "I love programming" is close to "I enjoy coding" and far from "The weather is nice" | `python learning/00-basics/similarity_test.py` |
| `rag_demo.py` | **RAG** in 4 steps on 3 hard-coded code snippets: embed → embed the question → pick the most similar snippet → ask the LLM with that snippet as context | `python learning/00-basics/rag_demo.py` |
| `index_and_query.py` | **A real index** — walk a whole project, split files into chunks, embed every chunk, save to JSON, then answer questions from it | `python learning/00-basics/index_and_query.py` (indexes `examples/demo_app`; pass another folder as an argument) |

## The one-paragraph explanation

An LLM knows nothing about *your* project. **RAG** (Retrieval-Augmented
Generation) fixes that: before asking the model, search the project for the
most relevant code and paste it into the prompt. Search works on *meaning*
because every chunk is turned into an **embedding** — a list of numbers — and
similar meanings have similar numbers (measured with **cosine similarity**:
1 = same direction, 0 = unrelated).

## What to notice

- `index_and_query.py` is deliberately naive: it embeds raw chunks and takes
  the top 3 by similarity. On a real project it can rank a translation file
  full of keywords like `login_email` above the actual login code. Phase 01
  fixes that.
- Minified one-line files break the chunker (a "line" can be longer than the
  embedding model accepts). Phase 01 fixes that too.

## Check your understanding

- Why does `similarity_test.py` score "love programming" vs "enjoy coding"
  higher than two sentences that share more words?
- In `rag_demo.py`, what would the model answer *without* step 3?
- Why not simply paste the whole project into the prompt?
