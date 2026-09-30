"""
run_eval.py — measure the agent instead of guessing.

Why this exists: we judged changes by one or two runs and got fooled by
noise (a change looked like a fix, then the next run failed). An eval runs
FIXED tasks several times and gives a number. A change is kept only if the
number goes up.

Usage (from the learn-agent folder, venv active):
  python -m evals.run_eval                    # all tasks, 2 runs each
  python -m evals.run_eval --runs 3
  python -m evals.run_eval --only add-logout review-fix
  python -m evals.run_eval --mode add         # compare edit strategies

Every run ALWAYS restores the file afterwards. Results are saved in
evals/results/ so you can compare before/after.
"""

import argparse
import contextlib
import difflib
import io
import json
import re
import time
from datetime import datetime
from pathlib import Path

from agent import cli, config, indexer, tools

HERE = Path(__file__).parent


def check(task, final):
    """PASS only if the checker passed AND the content checks hold."""
    content = final.get("new_content") or ""
    reasons = []
    if not final.get("passed"):
        reasons.append("checker failed")
    if content == final.get("original"):
        reasons.append("no change")
    for pattern in task["must_contain"]:
        if not re.search(pattern, content):
            reasons.append(f"missing /{pattern}/")
    for pattern in task["must_not_contain"]:
        if re.search(pattern, content):
            reasons.append(f"contains /{pattern}/")
    return not reasons, reasons


def run_one(task, index):
    """Run one task once, quietly, and always restore the file."""
    project = index["project_path"]
    start = time.time()
    log = io.StringIO()
    final, error = None, None
    try:
        with contextlib.redirect_stdout(log):  # keep the table readable
            final = cli.execute(task["task"], task["file"], index=index)
    except Exception as e:  # execute() already restored the file
        error = f"{type(e).__name__}: {e}"
    finally:
        if final is not None:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.restore(project, task["file"], final["original"])

    seconds = round(time.time() - start)
    if error:
        return {"passed": False, "reasons": [error], "attempts": None, "seconds": seconds}
    passed, reasons = check(task, final)
    diff = "\n".join(difflib.unified_diff(
        final["original"].splitlines(), (final.get("new_content") or "").splitlines(),
        lineterm="", n=1,
    ))
    return {"passed": passed, "reasons": reasons, "attempts": final["attempts"],
            "seconds": seconds, "diff": diff, "log": log.getvalue()[-3000:]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--only", nargs="*", help="task ids to run")
    parser.add_argument("--mode", default=config.EDIT_MODE, choices=["search_replace", "add", "auto"])
    args = parser.parse_args()

    config.EDIT_MODE = args.mode
    index = indexer.load_index()
    tasks = json.loads((HERE / "tasks.json").read_text())["tasks"]
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]

    # Refuse to start on dirty files: results would be meaningless.
    for t in tasks:
        _, out = tools.run_command(f"git status --porcelain -- '{t['file']}'", index["project_path"])
        if out.strip():
            raise SystemExit(f"{t['file']} has uncommitted changes — clean it first.")

    print(f"Model: {config.CHAT_MODEL} | mode: {args.mode} | runs per task: {args.runs}\n")
    results, total_pass, total = {}, 0, 0
    for t in tasks:
        runs = []
        for r in range(args.runs):
            res = run_one(t, index)
            runs.append(res)
            mark = "PASS" if res["passed"] else "fail"
            why = "" if res["passed"] else "  (" + "; ".join(res["reasons"])[:90] + ")"
            print(f"  {t['id']:<16} run {r + 1}: {mark}  attempts={res['attempts']}  {res['seconds']}s{why}")
        passes = sum(r["passed"] for r in runs)
        total_pass += passes
        total += len(runs)
        results[t["id"]] = runs
        print(f"  {t['id']:<16} => {passes}/{len(runs)}\n")

    print(f"SCORE: {total_pass}/{total} ({100 * total_pass // max(total, 1)}%)")

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = out_dir / f"{stamp}-{args.mode}.json"
    out.write_text(json.dumps({
        "model": config.CHAT_MODEL, "mode": args.mode, "runs": args.runs,
        "score": f"{total_pass}/{total}", "results": results,
    }, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
