"""
retriever.py — finds the chunks most relevant to a question.

Two-stage retrieval (the standard pattern in real RAG systems):

  Stage 1  FAST, ROUGH:   vector similarity over ALL chunks -> top 15
  Stage 2  SLOW, SMART:   ask the LLM to score those 15   -> top 4

Stage 1 alone is fooled by keyword overlap (ar.json full of "login_*" keys).
Stage 2 lets the model actually *read* the candidates and judge relevance.
"""

import math

from agent import config, llm


def cosine_similarity(a, b):
    """1.0 = pointing the same way (very similar), 0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.hypot(*a) * math.hypot(*b)
    return dot / norm if norm else 0.0


def vector_search(question, entries, limit=config.CANDIDATES):
    """Stage 1: rank every chunk by similarity to the question."""
    q_vec = llm.embed(question, kind="query")
    scored = []
    for entry in entries:
        score = cosine_similarity(q_vec, entry["embedding"])
        if entry.get("kind") == "data":
            score -= config.DATA_FILE_PENALTY  # prefer real code
        scored.append((score, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:limit]


def rerank(question, candidates, keep=config.TOP_K):
    """Stage 2: the LLM scores each candidate 0-10 in ONE call.

    We show only the first ~600 chars of each chunk to keep the prompt
    small enough for an 8B model."""
    listing = "\n\n".join(
        f"[{i}] File: {entry['path']}\n{entry['content'][:600]}"
        for i, (_, entry) in enumerate(candidates)
    )
    prompt = (
        f"Question: {question}\n\n"
        f"Below are numbered code snippets. Score how useful each one is "
        f"for answering the question, from 0 (useless) to 10 (essential).\n\n"
        f"{listing}\n\n"
        f'Reply as JSON: {{"scores": {{"0": 7, "1": 2, ...}}}}'
    )
    result = llm.chat_json([{"role": "user", "content": prompt}])
    scores = result.get("scores", {})

    if not scores:  # model misbehaved -> fall back to stage-1 order
        return [entry for _, entry in candidates[:keep]]

    ranked = sorted(
        range(len(candidates)),
        key=lambda i: float(scores.get(str(i), 0)),
        reverse=True,
    )
    return [candidates[i][1] for i in ranked[:keep]]


def retrieve(question, index, use_rerank=True, verbose=True):
    """Full retrieval: stage 1, then (optionally) stage 2."""
    if not index["entries"]:
        return []  # project not indexed yet (background indexing): no search results
    candidates = vector_search(question, index["entries"])
    if verbose:
        print("\nStage 1 (vector search):")
        for score, e in candidates:
            print(f"  [{score:.3f}] {e['kind']:4} {e['path']}:{e['start_line']}")

    if not use_rerank:
        return [e for _, e in candidates[: config.TOP_K]]

    top = rerank(question, candidates)
    if verbose:
        print("\nStage 2 (LLM rerank) kept:")
        for e in top:
            print(f"  {e['path']}:{e['start_line']}-{e['end_line']}")
    return top
