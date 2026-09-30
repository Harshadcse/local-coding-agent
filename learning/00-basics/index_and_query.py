import os
from pathlib import Path
import json
import math
import requests

EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
CHAT_URL = "http://localhost:11434/api/chat"
CHAT_MODEL = "llama3.1:8b"

# Folders to skip, across any tech stack
SKIP_DIRS = {
    ".git", "node_modules", "build", "dist", ".dart_tool", ".gradle",
    "Pods", ".idea", ".vscode", "__pycache__", "venv", ".venv",
    "target", "out", ".next", "coverage",
}

SKIP_FILENAMES = {".DS_Store"}

# File types to skip — binaries/generated files, not language-specific
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip",
    ".lock", ".min.js", ".map", ".woff", ".woff2", ".ttf",
    ".mp4", ".mp3", ".exe", ".dll", ".so", ".class", ".jar", ".pyc",
}

MAX_FILE_SIZE = 200_000  # skip absurdly large generated files
MAX_CHARS_PER_CHUNK = 6000  # conservative — well under typical embedding context limits


def find_source_files(project_path, extra_skip_dirs=None):
    """Walk a project folder and return every source file worth indexing,
    regardless of programming language."""
    skip_dirs = SKIP_DIRS | (extra_skip_dirs or set())
    source_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for filename in files:
            if filename in SKIP_FILENAMES:
                continue
            file_path = Path(root) / filename
            if file_path.suffix.lower() in SKIP_EXTENSIONS:
                continue
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE or file_path.stat().st_size == 0:
                    continue
            except OSError:
                continue
            source_files.append(str(file_path))
    return source_files


def chunk_text(text, max_chars=MAX_CHARS_PER_CHUNK):
    """Split text into chunks of at most max_chars, breaking on line boundaries."""
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_length = 0
    for line in lines:
        if current_length + len(line) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(line)
        current_length += len(line)
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


def get_embedding(text):
    """Call Ollama's embeddings endpoint for one piece of text."""
    payload = {"model": EMBED_MODEL, "prompt": text}
    response = requests.post(EMBED_URL, json=payload)
    data = response.json()
    if "embedding" not in data:
        print("UNEXPECTED RESPONSE:", data)
        raise ValueError("No embedding in response")
    return data["embedding"]


def build_index(file_paths):
    """Read, chunk, and embed every file. Skips anything that fails instead
    of crashing the whole run."""
    index = []
    for i, path in enumerate(file_paths, 1):
        try:
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"  skipped {path}: {e}")
            continue
        if not content.strip():
            continue

        chunks = chunk_text(content)
        print(f"  [{i}/{len(file_paths)}] {path} -> {len(chunks)} chunk(s)")

        for chunk_num, chunk in enumerate(chunks):
            try:
                embedding = get_embedding(chunk)
            except ValueError as e:
                print(f"    skipped chunk {chunk_num} of {path}: {e}")
                continue
            index.append({"path": path, "chunk": chunk_num, "content": chunk, "embedding": embedding})
    return index


def load_index(path):
    with open(path, "r") as f:
        return json.load(f)


def cosine_similarity(vec1, vec2):
    """How similar two vectors are, from -1 (opposite) to 1 (identical)."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.hypot(*vec1)
    magnitude2 = math.hypot(*vec2)
    return dot_product / (magnitude1 * magnitude2) if magnitude1 * magnitude2 != 0 else 0


def query(question, index, top_k=3):
    """Embed a question, retrieve the most relevant chunks from the index,
    and ask the local chat model to answer using them as context."""
    print(f"\nQuestion: {question}")
    question_embedding = get_embedding(question)

    scored = []
    for entry in index:
        score = cosine_similarity(question_embedding, entry["embedding"])
        scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_matches = scored[:top_k]

    print("\nTop matches:")
    for score, entry in top_matches:
        print(f"  [{score:.4f}] {entry['path']} (chunk {entry['chunk']})")

    context_parts = []
    for score, entry in top_matches:
        context_parts.append(f"File: {entry['path']}\n{entry['content']}")
    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""Here are relevant code snippets from the project:

{context}

Question: {question}

Answer using the style and patterns shown in the snippets above."""

    payload = {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    response = requests.post(CHAT_URL, json=payload)
    answer = response.json()["message"]["content"]

    print("\n=== ANSWER ===")
    print(answer)
    return answer


# ============================================================
# Step 1: find files + build the index (only the FIRST time, or when the
# project changes). Later runs load basics_index.json instead.
# ============================================================
import sys

HERE = Path(__file__).parent
INDEX_PATH = HERE / "basics_index.json"
project_path = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parent.parent / "examples" / "demo_app")

if not INDEX_PATH.exists():
    files = find_source_files(project_path)
    print(f"Found {len(files)} source files in {project_path}")
    print(f"\nEmbedding {len(files)} files (this can take a while)...")
    index = build_index(files)
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f)
    print(f"\nSaved {len(index)} embedded chunks to {INDEX_PATH.name}")


# ============================================================
# Step 2: load the existing index and ask questions against it
# ============================================================

index = load_index(INDEX_PATH)
print(f"Loaded {len(index)} chunks from {INDEX_PATH.name}")

query("how does login work in this app?", index)
# query("which class calls the HTTP API?", index)
# query("what naming convention is used for services?", index)
