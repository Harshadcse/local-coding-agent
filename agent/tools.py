"""
tools.py — the agent's "hands".

An LLM can only produce text. A *tool* is a plain Python function that does
something real (read a file, write a file, run a command). The agent loop
decides WHEN to call a tool; the tool does the work; the result goes back to
the LLM. That is the whole difference between a chatbot and an agent.

Safety rules built in:
  - Every path must stay inside the project folder (no writing to ~/.zshrc).
  - Commands run with a timeout.
"""

import os
import shutil
import subprocess
from pathlib import Path

from agent import config


def safe_path(project_path, rel_path):
    """Turn a relative path into an absolute one, refusing anything that
    escapes the project (e.g. "../../etc/passwd")."""
    root = Path(project_path).resolve()
    full = (root / rel_path).resolve()
    if root != full and root not in full.parents:
        raise ValueError(f"Path outside project: {rel_path}")
    return full


def read_file(project_path, rel_path):
    """Return file text, or "" if the file does not exist yet (new file)."""
    path = safe_path(project_path, rel_path)
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def write_file(project_path, rel_path, content):
    path = safe_path(project_path, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def delete_file(project_path, rel_path):
    path = safe_path(project_path, rel_path)
    if path.exists():
        path.unlink()


# Exit code 127 is the shell's way of saying "command not found".
TOOL_MISSING = 127


def tool_path():
    """PATH = the normal PATH + EXTRA_TOOL_PATHS from config."""
    extra = [os.path.expanduser(p) for p in config.EXTRA_TOOL_PATHS]
    return os.pathsep.join(extra + [os.environ.get("PATH", "")])


def run_command(command, cwd, timeout=180):
    """Run a shell command. Returns (exit_code, output).
    0 = success, TOOL_MISSING = the program itself was not found."""
    env = {**os.environ, "PATH": tool_path()}
    try:
        result = subprocess.run(
            command, shell=True, cwd=cwd, env=env,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, f"Command timed out after {timeout}s: {command}"
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output[-4000:]  # last 4000 chars is enough for errors


# ---------- Verification: language-agnostic by detection ----------
# We look at marker files in the project to guess the right checker.
# "{file}" is replaced with the file the agent edited.
# Add a row here to support a new technology — no other code changes needed.
VERIFY_RULES = [
    # (marker file,     required tool, command)
    ("pubspec.yaml",    "dart",   "dart analyze {file}"),
    ("tsconfig.json",   "npx",    "npx --no-install tsc --noEmit"),
    ("package.json",    "node",   "node --check {file}"),
    ("go.mod",          "go",     "go vet ./..."),
    ("Cargo.toml",      "cargo",  "cargo check --quiet"),
    ("pyproject.toml",  "python3", "python3 -m py_compile {file}"),
    ("requirements.txt", "python3", "python3 -m py_compile {file}"),
]


def detect_verify_command(project_path):
    """Return a verify command template for this project, or None.
    Prints why, so the user always knows what (if anything) is checked."""
    root = Path(project_path)
    for marker, tool, command in VERIFY_RULES:
        if (root / marker).exists():
            if shutil.which(tool, path=tool_path()):
                return command
            print(f"(found {marker} but '{tool}' is not on PATH — skipping verify)")
            return None
    return None
