"""
config.py — every setting in ONE place.

Why: when you want to try a different model or tweak retrieval, you change
it here instead of hunting through the code. Nothing here is tied to a
specific programming language.
"""

import os

# ---------- Ollama (the local LLM server) ----------
OLLAMA_URL = "http://localhost:11434"

# Chat model: the "brain" that writes answers and code.
# qwen2.5-coder is trained specifically on code and is usually better than
# llama3.1 at the same size. Install it with:  ollama pull qwen2.5-coder:7b
# Until then, llama3.1:8b works fine.
CHAT_MODEL = "qwen2.5-coder:7b"   # was "llama3.1:8b"

# Embedding model: turns text into a list of numbers (a "vector") so we can
# measure how similar two pieces of text are.
EMBED_MODEL = "nomic-embed-text"

# Context window in tokens (how much text the model can "see" at once).
# Ollama's default is small; editing whole files needs more. 16k fits in
# 16GB RAM for an 8B model. Lower it if your Mac starts swapping.
NUM_CTX = 16384

# Randomness of the model. 0 = same prompt -> same answer, which makes runs
# reproducible and debuggable. (Retries still differ: their prompt has new errors.)
TEMPERATURE = 0

# Max tokens the model may WRITE per reply. Stops runaway replies (a model
# stuck repeating itself can otherwise run for 10+ minutes). An edit reply
# is normally a few hundred tokens.
MAX_OUTPUT_TOKENS = 2048

# ---------- Indexing ----------
INDEX_FILE = "agent_index.json"  # CLI index; the server keeps one per project in indexes/

# Folders we never want to read, across any tech stack.
SKIP_DIRS = {
    ".git", "node_modules", "build", "dist", ".dart_tool", ".gradle",
    "Pods", ".idea", ".vscode", "__pycache__", "venv", ".venv",
    "target", "out", ".next", "coverage",
}
SKIP_FILENAMES = {".DS_Store"}

# Binary / generated files — useless to an LLM.
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip",
    ".lock", ".map", ".woff", ".woff2", ".ttf", ".xcuserstate",
    ".mp4", ".mp3", ".exe", ".dll", ".so", ".class", ".jar", ".pyc",
}

# "Data" files: they are not code (translations, configs, docs).
# We still index them, but rank them lower for code questions.
# This fixes "a translation JSON full of login_* keys beat the real login code".
DATA_EXTENSIONS = {
    ".json", ".arb", ".yaml", ".yml", ".xml", ".plist", ".csv",
    ".md", ".txt", ".properties", ".toml", ".ini", ".env",
}

MAX_FILE_SIZE = 200_000     # bytes; bigger files are usually generated
MAX_CHUNK_CHARS = 3000      # smaller chunks = more precise search results
MAX_LINE_CHARS = 1000       # a "line" longer than this is minified junk

# ---------- Retrieval ----------
CANDIDATES = 15             # step 1: grab this many by vector similarity
TOP_K = 4                   # step 2: keep this many after reranking
DATA_FILE_PENALTY = 0.10    # subtract from score for data files

# ---------- Agent (Phase 2) ----------
MAX_ATTEMPTS = 5            # how many times to retry after a failed verify

# Extra folders to search for tools like dart, flutter, go, cargo — added to
# PATH only for commands the agent runs. Set AGENT_TOOL_PATHS if a tool is not
# on your PATH, e.g.  export AGENT_TOOL_PATHS=~/flutter/bin:~/go/bin
EXTRA_TOOL_PATHS = [p for p in os.environ.get("AGENT_TOOL_PATHS", "").split(":") if p]

# Print the model's raw replies (set env AGENT_DEBUG=1). Essential for
# understanding WHY the agent did something.
DEBUG = os.environ.get("AGENT_DEBUG") == "1"

# How the model's edit is applied:
#   "search_replace" — model returns SEARCH/REPLACE blocks (or a whole file)
#   "add"            — model returns only NEW code + imports; our program inserts them
#   "auto"           — escalation: "add" for the first ADD_MODE_ATTEMPTS attempts
#                      (fast, accurate on clear tasks), then "search_replace"
#                      (slower, but better at working through errors).
# Chosen by measurement: see evals/ and docs/PHASE_2_5.md.
EDIT_MODE = "search_replace"   # best measured: 7/10 (add: 6/10 but 5x faster)
ADD_MODE_ATTEMPTS = 2
