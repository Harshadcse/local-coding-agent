"""
standards.py — Phase 3: check a file against a coding-standards checklist.

Three sources, from most to least reliable:
  1. LINTER  — the project's own analyzer (dart analyze, eslint, ...)
  2. REGEX   — rules with a `pattern:` line. Exact, instant, never hallucinate.
  3. LLM     — rules without a pattern. The model reads the numbered file and
               reports violations as JSON. We then VALIDATE its answer (the rule
               must exist, the line must exist) and drop anything invented.

Language-agnostic: the rules are plain text, the linter is auto-detected.
"""

import re
from pathlib import Path

from agent import llm, tools

DEFAULT_STANDARDS = Path(__file__).parent.parent / "standards" / "default.md"


def load_rules(project_path, path=None):
    """Read rules from: --standards path, else <project>/.agent/standards.md,
    else the default checklist. Returns [{"id", "text", "pattern"}]."""
    candidates = [path, Path(project_path) / ".agent" / "standards.md", DEFAULT_STANDARDS]
    source = next(Path(p) for p in candidates if p and Path(p).exists())
    rules = []
    for line in source.read_text().splitlines():
        header = re.match(r"^##\s*([\w-]+)\s*:\s*(.+)$", line)
        if header:
            rules.append({"id": header.group(1), "text": header.group(2).strip(), "pattern": None})
        elif line.startswith("pattern:") and rules:
            rules[-1]["pattern"] = line[len("pattern:"):].strip()
    print(f"[standards] {len(rules)} rules from {source}")
    return rules


def check_file(project_path, rel_path, rules, use_llm=True):
    """Return a list of violations: {"source", "rule", "line", "reason"}."""
    content = tools.read_file(project_path, rel_path)
    lines = content.splitlines()
    violations = []

    # 1. Linter (only its error/warning lines)
    command = tools.detect_verify_command(project_path)
    if command:
        _, output = tools.run_command(command.format(file=rel_path), project_path)
        for out_line in output.splitlines():
            m = re.search(r"(error|warning|info)\s+-\s+[^:]+:(\d+):\d+\s+-\s+(.+?)(?:\s+-\s+[\w_]+)?$", out_line)
            if m:
                violations.append({"source": "linter", "rule": m.group(1),
                                   "line": int(m.group(2)), "reason": m.group(3)})

    # 2. Regex rules
    for rule in rules:
        if not rule["pattern"]:
            continue
        regex = compile_pattern(rule["pattern"])
        for n, line in enumerate(lines, 1):
            if regex.search(line):
                violations.append({"source": "regex", "rule": rule["id"], "line": n,
                                   "reason": rule["text"]})

    # 3. LLM rules
    llm_rules = [r for r in rules if not r["pattern"]]
    if use_llm and llm_rules:
        violations += llm_check(rel_path, lines, llm_rules)

    return sorted(violations, key=lambda v: v["line"])


def compile_pattern(pattern):
    """Support a leading/inline (?i) anywhere, which Python only allows at the start."""
    flags = re.IGNORECASE if "(?i)" in pattern else 0
    return re.compile(pattern.replace("(?i)", ""), flags)


def review_file(rel_path, content, guidelines, focus=""):
    """Code review of one file against free-form guidelines (e.g. the user's
    coding_standard.md). Returns validated findings:
    [{"line", "rule", "problem", "suggestion", "code"}], sorted by line."""
    lines = content.splitlines()
    numbered = "\n".join(f"{n:4}| {l}" for n, l in enumerate(lines, 1))
    prompt = f"""You are a strict code reviewer. Review the file below.
{"Guidelines to check against:" + chr(10) + guidelines if guidelines else "Use general best practices for this language."}
{("Focus on: " + focus) if focus else ""}

File {rel_path} (line numbers on the left):
{numbered}

List concrete problems in THIS file. Report each problem ONCE (if it repeats,
report the first place). For each: the line number, the exact code on that
line that shows the problem ("quote"), which guideline it breaks (short name),
what is wrong, and how to fix it. Do not report something the code already
does correctly. No praise, no generic advice.
Reply as JSON: {{"findings": [{{"line": <number>, "quote": "<exact code from that line>", "rule": "<short name>", "problem": "<what is wrong>", "suggestion": "<how to fix>"}}]}}"""
    result = llm.chat_json([{"role": "user", "content": prompt}])

    found, seen = [], set()
    for f in result.get("findings", []) if isinstance(result, dict) else []:
        try:
            line = int(f.get("line", 0))
        except (TypeError, ValueError):
            continue
        problem = str(f.get("problem", "")).strip()
        if not (1 <= line <= len(lines)) or not problem:
            continue
        # Evidence check: the quoted code must really be at/near that line.
        # Drops invented findings (e.g. "uses print()" where there is none).
        line = locate_quote(lines, line, str(f.get("quote", "")))
        if line is None:
            continue
        # Same rule + same problem = one finding (models repeat themselves).
        key = (str(f.get("rule", "")).lower(), problem.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append({"line": line, "rule": str(f.get("rule", ""))[:60],
                      "problem": problem[:300],
                      "suggestion": str(f.get("suggestion", ""))[:300],
                      "code": lines[line - 1].strip()[:120]})
    return sorted(found, key=lambda f: f["line"])


def locate_quote(lines, line, quote, window=2):
    """Line number (1-based) near `line` that contains `quote`, else None."""
    q = " ".join(quote.split())
    if len(q) < 3:
        return None
    for n in [line] + [line + d for k in range(1, window + 1) for d in (-k, k)]:
        if 1 <= n <= len(lines) and q in " ".join(lines[n - 1].split()):
            return n
    return None


def llm_check(rel_path, lines, rules):
    numbered = "\n".join(f"{n:4}| {l}" for n, l in enumerate(lines, 1))
    rule_list = "\n".join(f"- {r['id']}: {r['text']}" for r in rules)
    prompt = f"""Review this file against the rules below. Report ONLY clear violations.

Rules:
{rule_list}

File {rel_path} (line numbers on the left):
{numbered}

Reply as JSON: {{"violations": [{{"rule": "<rule id>", "line": <number>, "reason": "<short reason>"}}]}}
If there are no violations, reply {{"violations": []}}."""
    result = llm.chat_json([{"role": "user", "content": prompt}])

    # Validate: a small model can invent rule ids or line numbers.
    valid_ids = {r["id"] for r in rules}
    found = []
    for v in result.get("violations", []) if isinstance(result, dict) else []:
        try:
            line = int(v.get("line", 0))
        except (TypeError, ValueError):
            continue
        if v.get("rule") in valid_ids and 1 <= line <= len(lines):
            found.append({"source": "llm", "rule": v["rule"], "line": line,
                          "reason": str(v.get("reason", ""))[:200]})
    return found


def format_report(rel_path, violations, lines):
    if not violations:
        return f"{rel_path}: no violations found"
    out = [f"{rel_path}: {len(violations)} violation(s)"]
    for v in violations:
        code = lines[v["line"] - 1].strip()[:70] if v["line"] <= len(lines) else ""
        out.append(f"  line {v['line']:<4} [{v['source']}:{v['rule']}] {v['reason']}\n             > {code}")
    return "\n".join(out)


def fix_task(violations):
    """Turn violations into a task for the Phase 2 agent."""
    items = "\n".join(f"- line {v['line']}: [{v['rule']}] {v['reason']}" for v in violations)
    return ("Fix these coding-standard violations. Change only what is needed for "
            f"each one and keep all other code unchanged:\n{items}")
