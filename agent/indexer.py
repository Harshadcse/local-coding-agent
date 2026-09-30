"""
indexer.py — reads a project and builds the searchable index.

Pipeline:  find files  ->  split into chunks  ->  embed each chunk  ->  save JSON

Each saved entry looks like:
  {"path": "lib/services/auth_service.dart", "chunk": 0, "kind": "code",
   "start_line": 1, "end_line": 80, "content": "...", "embedding": [...]}
"""

import json
import os
from pathlib import Path

from agent import config, llm


def find_source_files(project_path, extra_skip_dirs=None):
    """Walk the project and return paths of every text file worth indexing.
    Works for any language because we skip by *what is junk*, not by
    *what language it is*."""
    skip_dirs = config.SKIP_DIRS | set(extra_skip_dirs or [])
    found = []
    for root, dirs, files in os.walk(project_path):
        # Editing dirs in place tells os.walk not to go into those folders.
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for name in files:
            path = Path(root) / name
            if name in config.SKIP_FILENAMES or path.suffix.lower() in config.SKIP_EXTENSIONS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if 0 < size <= config.MAX_FILE_SIZE:
                found.append(path)
    return found


def file_kind(path):
    """'data' for translations/config/docs, 'code' for everything else."""
    return "data" if Path(path).suffix.lower() in config.DATA_EXTENSIONS else "code"


def chunk_text(text, max_chars=config.MAX_CHUNK_CHARS):
    """Split text into chunks on line boundaries.
    Returns a list of (start_line, end_line, chunk_text).

    Line numbers matter later: the agent will need them to say *where*
    something is and to edit the right lines."""
    chunks = []
    current, size, start = [], 0, 1
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line[: config.MAX_LINE_CHARS]  # tame minified one-line files
        if size + len(line) > max_chars and current:
            chunks.append((start, line_no - 1, "\n".join(current)))
            current, size, start = [], 0, line_no
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append((start, start + len(current) - 1, "\n".join(current)))
    return chunks


def build_index(project_path, extra_skip_dirs=None, out_file=None, progress=None):
    """Index a whole project and save it to out_file (default config.INDEX_FILE).
    progress(done, total) is called after each file (used for the progress
    shown in VS Code while indexing runs in the background)."""
    project_path = Path(project_path).resolve()
    files = find_source_files(project_path, extra_skip_dirs)
    print(f"Found {len(files)} files. Embedding (this takes a while)...")

    entries = []
    for i, path in enumerate(files, 1):
        rel_path = str(path.relative_to(project_path))
        if progress:
            progress(i, len(files))
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            continue
        chunks = chunk_text(text)
        print(f"  [{i}/{len(files)}] {rel_path} -> {len(chunks)} chunk(s)")

        for n, (start, end, content) in enumerate(chunks):
            # KEY FIX: put the file path in front of the text we embed.
            # A path like "services/auth_service.dart" tells the model
            # what the code is *for*, much better than the code alone.
            text_to_embed = f"File: {rel_path}\n\n{content}"
            try:
                vector = llm.embed(text_to_embed, kind="document")
            except Exception as e:
                print(f"    skipped chunk {n}: {e}")
                continue
            entries.append({
                "path": rel_path, "chunk": n, "kind": file_kind(path),
                "start_line": start, "end_line": end,
                "content": content, "embedding": vector,
            })

    index = {"project_path": str(project_path), "entries": entries}
    out_file = out_file or config.INDEX_FILE
    with open(out_file, "w") as f:
        json.dump(index, f)
    print(f"\nSaved {len(entries)} chunks to {out_file}")
    return index


def load_index():
    return load_index_from(config.INDEX_FILE)


def load_index_from(path):
    with open(path) as f:
        return json.load(f)
