"""
cli.py — command-line entry point for the agent.

Usage (run from the learn-agent folder, with the venv active):
  python -m agent.cli index examples/demo_app
  python -m agent.cli ask "how is login implemented?"
  python -m agent.cli ask "how is login implemented?" --no-rerank   # compare!
  python -m agent.cli do "add input validation to the login form"
  python -m agent.cli do "..." --file lib/x.dart --verify "dart analyze {file}"
"""

import argparse
import difflib

from agent import config, indexer, llm, retriever, tools

SYSTEM_PROMPT = """You are a coding assistant for the user's project.
Answer ONLY from the code snippets provided. Always mention the file path
you are referring to. If the snippets do not contain the answer, say so
instead of guessing. When writing new code, follow the style and patterns
used in the snippets."""


def answer(question, use_rerank=True):
    index = indexer.load_index()
    chunks = retriever.retrieve(question, index, use_rerank=use_rerank)

    context = "\n\n---\n\n".join(
        f"File: {c['path']} (lines {c['start_line']}-{c['end_line']})\n{c['content']}"
        for c in chunks
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Code snippets:\n\n{context}\n\nQuestion: {question}"},
    ]
    print("\n=== ANSWER ===")
    reply = llm.chat(messages)
    print(reply)
    return reply


def run_agent(task, target_file=None, verify_command=None, auto_yes=False, extra_state=None):
    """Phase 2: run the LangGraph agent, then let the human approve the diff."""
    final = execute(task, target_file, verify_command, extra_state=extra_state)
    project_path = final["project_path"]

    # ---- Human in the loop: show the diff, ask before keeping it ----
    path = final["target_file"]
    diff = difflib.unified_diff(
        final["original"].splitlines(), final["new_content"].splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    )
    print("\n=== DIFF ===")
    print("\n".join(diff) or "(no changes)")
    # Like Copilot/Claude: surface every placeholder the agent left for you.
    todos = [l.strip() for l in final["new_content"].splitlines()
             if "TODO" in l and l not in final["original"]]
    if todos:
        print("\n=== NEEDS YOUR ATTENTION ===")
        for t in todos:
            print(f"  {t}")

    status = "passed" if final.get("passed") else "FAILED"
    print(f"\nVerify: {status}  |  attempts: {final['attempts']}")

    keep = auto_yes or input("\nKeep this change? [y/N] ").strip().lower() == "y"
    if keep:
        print(f"Kept changes in {path}")
    else:
        restore(project_path, path, final["original"])


class AgentCancelled(Exception):
    """Raised between graph steps when the user pressed Stop."""


def execute(task, target_file=None, verify_command=None, index=None, extra_state=None,
            should_stop=None, require_clean=True):
    """Run the agent graph and return its final state. The edited file is
    left on disk; the caller decides to keep or restore it. Used by both the
    CLI (asks a human) and the evaluation harness (always restores).
    should_stop: optional function; if it returns True, the run stops after
    the current step and the original file is restored.
    require_clean: refuse files with uncommitted changes (CLI). The server
    passes False: in the editor, uncommitted changes are the user's normal
    work (e.g. a proposal they just accepted), and the server always restores
    the file after a run."""
    from agent.graph import build_graph  # imported here so 'ask' works without langgraph

    index = index or indexer.load_index()
    project_path = index["project_path"]

    # Editing a file that does not exist would silently start from an EMPTY
    # file (this happened: a wrong relative path made the proposal look like
    # "delete every line"). Creating new files must be explicit.
    if target_file and not tools.safe_path(project_path, target_file).exists():
        raise SystemExit(f"File not found in the indexed project ({project_path}): {target_file}")

    # Safety: never start on a file with uncommitted changes. The agent could
    # not tell the user's edits from a leftover run (this happened: a run left
    # waiting at the prompt made every later test start from broken code).
    if target_file and require_clean:
        code, out = tools.run_command(f"git status --porcelain -- '{target_file}'", project_path)
        if code == 0 and out.strip():
            raise SystemExit(
                f"{target_file} has uncommitted changes. Commit/stash them, or "
                f"finish the other agent run (answer its y/N prompt), then try again."
            )

    if verify_command is None:
        verify_command = tools.detect_verify_command(project_path)

    # Errors the file ALREADY has, so a task like "fix error" knows what to fix.
    existing_errors = ""
    if verify_command and target_file:
        code, out = tools.run_command(verify_command.format(file=target_file), project_path)
        if code not in (0, tools.TOOL_MISSING):
            existing_errors = out

    inputs = {
        "task": task,
        "project_path": project_path,
        "index": index,
        "target_file": target_file,
        "verify_command": verify_command,
        "attempts": 0,
        "existing_errors": existing_errors,
        **(extra_state or {}),
    }

    # stream() yields the full state after every node, so we always know the
    # latest state. If ANYTHING goes wrong (timeout, Ctrl+C, bug), we can
    # still put the original file back. An agent must never leave a
    # half-edited file behind.
    final = None
    try:
        for state in build_graph().stream(inputs, stream_mode="values"):
            final = state
            if should_stop and should_stop():
                raise AgentCancelled("stopped by user")
    except BaseException as error:
        if final and final.get("original") is not None:
            restore(project_path, final["target_file"], final["original"])
            print(f"\n[error] {type(error).__name__}: {error} — original file restored.")
        raise
    return final


def restore(project_path, path, original):
    """Put the file back exactly as it was ("" = it did not exist before)."""
    if original:
        tools.write_file(project_path, path, original)
        print("Reverted to the original file.")
    else:
        tools.delete_file(project_path, path)
        print("Removed the new file.")


def check(rel_path, standards_path=None, use_llm=True):
    """Phase 3: report coding-standard violations for one file."""
    from agent import standards
    project_path = indexer.load_index()["project_path"]
    rules = standards.load_rules(project_path, standards_path)
    violations = standards.check_file(project_path, rel_path, rules, use_llm)
    lines = tools.read_file(project_path, rel_path).splitlines()
    print("\n" + standards.format_report(rel_path, violations, lines))
    return violations


def fix(rel_path, standards_path=None, use_llm=True, auto_yes=False):
    """Phase 3: check, then let the Phase 2 agent fix the violations."""
    from agent import standards
    violations = check(rel_path, standards_path, use_llm)
    if not violations:
        return
    # Fixes change/remove existing lines: search/replace mode, deletions allowed.
    config.EDIT_MODE = "search_replace"
    run_agent(standards.fix_task(violations), rel_path, auto_yes=auto_yes,
              extra_state={"allow_deletions": True})


def main():
    parser = argparse.ArgumentParser(description="Local offline coding agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="index a project folder")
    p_index.add_argument("project_path")
    p_index.add_argument("--skip", nargs="*", default=[], help="extra folders to skip")

    p_ask = sub.add_parser("ask", help="ask a question about the indexed project")
    p_ask.add_argument("question")
    p_ask.add_argument("--no-rerank", action="store_true")

    p_do = sub.add_parser("do", help="let the agent change code (Phase 2)")
    p_do.add_argument("task")
    p_do.add_argument("--file", help="file to edit (skip the plan step)")
    p_do.add_argument("--verify", help='checker command, e.g. "dart analyze {file}"')
    p_do.add_argument("--yes", action="store_true", help="keep changes without asking")
    p_do.add_argument("--mode", choices=["search_replace", "add", "auto"],
                      help="edit strategy (default: EDIT_MODE in config.py)")

    for name, helptext in [("check", "check a file against coding standards (Phase 3)"),
                           ("fix", "check a file, then let the agent fix violations (Phase 3)")]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("file", help="file path relative to the indexed project")
        p.add_argument("--standards", help="rules file (default: <project>/.agent/standards.md or standards/default.md)")
        p.add_argument("--no-llm", action="store_true", help="only linter + regex rules (fast)")
        if name == "fix":
            p.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    if args.command == "index":
        indexer.build_index(args.project_path, args.skip)
    elif args.command == "ask":
        answer(args.question, use_rerank=not args.no_rerank)
    elif args.command == "do":
        if args.mode:
            config.EDIT_MODE = args.mode
        run_agent(args.task, args.file, args.verify, args.yes)

    elif args.command == "check":
        check(args.file, args.standards, not args.no_llm)
    elif args.command == "fix":
        fix(args.file, args.standards, not args.no_llm, args.yes)


if __name__ == "__main__":
    main()
