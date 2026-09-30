"""
graph.py — the agent loop, built with LangGraph.

LangGraph in three ideas:
  1. STATE  — one dictionary that every step can read and update.
  2. NODES  — plain Python functions: take the state, return the fields
              they changed.
  3. EDGES  — which node runs next. A *conditional* edge picks the next node
              by looking at the state. That is how we get a LOOP.

Our graph:

    retrieve ──► plan ──► generate ──► write ──► verify ──► END (passed)
                           ▲   │                  │
                           │   └─ edits didn't ───┤
                           │      match: retry    │
                           └──── lookup ◄─────────┘ (check failed)

Every loop back counts as an attempt; after MAX_ATTEMPTS we stop.
Edits are SEARCH/REPLACE blocks (see editor.py), not whole-file rewrites.

"Self-healing": if verify fails, the `lookup` step reads the error, finds
the names it complains about (e.g. 'logoutUrl'), and searches the project
for them. The model retries with the errors AND the real definitions — or
a clear "this does not exist". Errors alone are not enough: without new
facts, a model tends to repeat the same mistake.
"""

import difflib
import re
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent import config, editor, llm, retriever, tools


# ---------- 1. STATE ----------
class AgentState(TypedDict, total=False):
    task: str               # what the user asked for
    project_path: str       # root folder of the project
    index: dict             # the Phase 1 index (for retrieval)
    context: list           # retrieved chunks
    target_file: str        # relative path of the file to edit
    original: str           # file content BEFORE we touched it (for undo)
    new_content: str        # latest generated file content
    verify_command: str     # e.g. "dart analyze {file}", or None
    passed: bool            # did the last verify succeed?
    verify_broken: bool     # checker itself could not run (not the code's fault)
    errors: str             # verify output when it failed
    facts: str              # what lookup found about names in the errors
    allow_deletions: bool   # fix runs may remove lines (deletion guard off)
    edit_errors: str        # SEARCH/REPLACE blocks that did not match the file
    existing_errors: str    # checker errors the file had BEFORE the agent started
    extra_context: str      # files the user added as context (e.g. coding_standard.md)
    attempts: int           # how many times we have generated


# ---------- 2. NODES ----------
def retrieve_node(state):
    """Find code related to the task (reuses Phase 1 exactly)."""
    print("\n[retrieve] searching the project...")
    query = state["task"]
    if state.get("target_file"):
        # The file name is a strong hint ("auth_service" -> login code).
        query += f" (in {state['target_file']})"
    chunks = retriever.retrieve(query, state["index"], verbose=False)
    for c in chunks:
        print(f"  {c['path']}:{c['start_line']}-{c['end_line']}")
    return {"context": chunks}


def plan_node(state):
    """Decide WHICH file to change. Skipped if the user gave --file."""
    if state.get("target_file"):
        print(f"\n[plan] using file given by user: {state['target_file']}")
        return {}

    candidates = sorted({c["path"] for c in state["context"]})
    prompt = (
        f"Task: {state['task']}\n\n"
        f"Relevant files in the project:\n" + "\n".join(f"- {p}" for p in candidates) +
        "\n\nWhich ONE file should be edited to do this task? You may also "
        "propose a NEW file path if none fits. Reply as JSON: "
        '{"file": "relative/path", "reason": "short reason"}'
    )
    result = llm.chat_json([{"role": "user", "content": prompt}])
    target = result.get("file") or candidates[0]
    print(f"\n[plan] edit {target} — {result.get('reason', 'top retrieval hit')}")
    return {"target_file": target}


def generate_node(state):
    """Ask the model for an edit and apply it (see editor.py).

    KEY DESIGN (learned the hard way):
      - Every attempt starts from the ORIGINAL file. If attempt 2 built on
        attempt 1's broken file, the model added a second copy of the method.
      - A retry is a short, FOCUSED repair prompt: "you wrote this, the checker
        says that, fix it". Tested alone, the 7B model fixed the error at once;
        buried in a 5000-token prompt, it failed 4 times in a row."""
    attempt = state.get("attempts", 0) + 1
    print(f"\n[generate] attempt {attempt}/{config.MAX_ATTEMPTS} ({edit_mode(attempt)} mode)...")

    # Remember the original only once, so we can always undo.
    original = state.get("original")
    if original is None:
        original = tools.read_file(state["project_path"], state["target_file"])

    is_retry = bool(state.get("errors") or state.get("edit_errors"))
    if config.EDIT_MODE == "auto" and attempt == config.ADD_MODE_ATTEMPTS + 1:
        # Switching strategy = FRESH START. Measured: once stuck, the model
        # copies its previous wrong code in every repair; a fresh first draft
        # (without that code in view) often takes a different, working approach.
        is_retry = False
        print("[generate] switching strategy: fresh start")
    prompt = repair_prompt(state, original) if is_retry else first_prompt(state, original)

    # Attempt 1 is deterministic (temperature 0). On retries we allow a little
    # randomness: with temperature 0 and the same errors, the model would give
    # the SAME wrong answer every time (we saw it repeat one mistake 4 times).
    temperature = 0 if attempt == 1 else 0.4
    reply = llm.chat([
        {"role": "system", "content": "You are a careful senior developer editing one file."},
        {"role": "user", "content": prompt},
    ], temperature=temperature)

    if config.DEBUG:
        print(f"----- raw model reply -----\n{reply}\n---------------------------")
    if edit_mode(attempt) == "add":
        new_content, problems = editor.apply_add(original, reply)
    else:
        # Fix runs (Phase 3) must be allowed to remove lines, e.g. a print().
        new_content, problems = editor.apply_reply(
            original, reply, original, allow_deletions=state.get("allow_deletions", False))
    print(f"[generate] {'edit rejected' if problems else 'edit applied'}")

    return {
        "new_content": new_content,
        "original": original,
        "attempts": attempt,
        "edit_errors": "\n\n".join(problems),
    }


RULES = """Rules:
- Only use classes, methods, fields and URLs that exist in the code shown. Never invent them.
- If the task needs something that does not exist (e.g. an API URL), add a clearly
  named placeholder with a comment starting with 'TODO:' so the developer can fill it in.
  Still write the rest of the logic, following the pattern of similar existing methods.
- The code must compile."""


def edit_mode(attempt):
    """Which edit strategy this attempt uses (see config.EDIT_MODE)."""
    if config.EDIT_MODE == "auto":
        return "add" if attempt <= config.ADD_MODE_ATTEMPTS else "search_replace"
    return config.EDIT_MODE


def format_help(attempt):
    """The reply format depends on the edit mode."""
    return editor.ADD_FORMAT_HELP if edit_mode(attempt) == "add" else editor.EDIT_FORMAT_HELP


def first_prompt(state, original):
    """Attempt 1: task + related code + the file + rules + edit format."""
    context = "\n\n".join(
        f"File: {c['path']}\n{c['content']}"
        for c in state["context"] if c["path"] != state["target_file"]
    )
    return f"""Task: {state['task']}
{guidelines_note(state)}
Related code from the project (for style and APIs, do NOT edit these):
{context or '(none)'}

File to edit: {state['target_file']}
```
{original or '(new empty file)'}
```
{existing_errors_note(state)}
{RULES}

{format_help(state.get('attempts', 0) + 1)}"""


def guidelines_note(state):
    """Files the user added as context (standards, docs): follow them."""
    if not state.get("extra_context"):
        return ""
    return f"\nProject guidelines / context provided by the user (FOLLOW these):\n{state['extra_context']}\n"


def existing_errors_note(state):
    """Checker errors already in the file (lets 'fix error' tasks work)."""
    if not state.get("existing_errors"):
        return ""
    return f"\nThe file currently has these checker errors (fix them if the task asks):\n{state['existing_errors']}\n"


def repair_prompt(state, original):
    """Attempts 2+: SHORT and focused. No retrieved context — just the file,
    what the model changed last time, and exactly what was wrong with it."""
    attempt = state.get("attempts", 0) + 1
    if edit_mode(attempt) == "add" and state.get("errors"):
        return minimal_add_repair_prompt(state, original)
    previous_change = "\n".join(difflib.unified_diff(
        original.splitlines(), state.get("new_content", original).splitlines(),
        lineterm="", n=2,
    ))
    problems = state.get("edit_errors") or state.get("errors")
    facts = f"\nFacts:\n{state['facts']}\n" if state.get("facts") and not state.get("edit_errors") else ""
    return f"""Task: {state['task']}

File to edit: {state['target_file']}
```
{original}
```

Your previous attempt made this change (diff against the file above):
```diff
{previous_change or '(no change was applied)'}
```

It FAILED with:
{problems}
{facts}
{guidelines_note(state)}
Write a corrected version of your change, applied to the file shown above.
{RULES}

{format_help(state.get('attempts', 0) + 1)}"""


def minimal_add_repair_prompt(state, original):
    """The smallest possible repair prompt: ONLY the code the model added,
    the errors and the facts. No file, no rules, no retrieved context.
    Measured reason: in the isolated test this shape fixed the error at once,
    while longer repair prompts made the model repeat its mistake 4-5 times."""
    new_lines = (state.get("new_content") or "").splitlines()
    old_lines = set(original.splitlines())
    added = "\n".join(l for l in new_lines if l not in old_lines)
    facts = f"\nFacts:\n{state['facts']}\n" if state.get("facts") else ""
    return f"""You added this code to {state['target_file']} for the task "{state['task']}":
```
{added}
```

The analyzer reports:
{state['errors']}
{facts}
Fix ALL the errors. If a name does not exist, do not use it: use a placeholder
with a 'TODO:' comment instead.

{editor.ADD_FORMAT_HELP}"""


def write_node(state):
    """Save the generated content to disk (the verify step needs a real file)."""
    tools.write_file(state["project_path"], state["target_file"], state["new_content"])
    print(f"[write] saved {state['target_file']}")
    return {}


def verify_node(state):
    """Run the project's checker (analyzer / compiler) on the edited file."""
    command = state.get("verify_command")
    if not command:
        print("[verify] no checker for this project — skipped")
        return {"passed": True, "errors": ""}

    cmd = command.format(file=state["target_file"])
    print(f"[verify] {cmd}")
    exit_code, output = tools.run_command(cmd, cwd=state["project_path"])

    # A missing tool is an ENVIRONMENT problem. Retrying cannot fix it, and
    # feeding "command not found" to the model would just confuse it.
    if exit_code == tools.TOOL_MISSING:
        print(f"  CHECKER NOT FOUND: {output}\n  (add its folder to EXTRA_TOOL_PATHS in config.py)")
        return {"passed": False, "verify_broken": True, "errors": output}

    passed = exit_code == 0
    print("  PASSED" if passed else f"  FAILED:\n{indent(output)}")
    return {"passed": passed, "errors": "" if passed else output}


# Words that look like names in error messages but are not project code.
NOT_SYMBOLS = {
    "type", "the", "a", "an", "int", "String", "void", "dynamic", "Object",
    # language keywords that show up quoted in error messages
    "static", "const", "final", "var", "let", "async", "await", "new", "this",
    "null", "return", "class", "import", "public", "private", "self", "def",
}

# How a name is *defined* in most languages. Add keywords for new languages here.
# STRONG = the name right after the keyword ("class AppLogger").
# WEAK   = variables/fields, which also match *usages* ("final AppLogger x"),
#          so we only trust them when no strong definition exists.
STRONG_DEFINITION = (
    r"\b(class|struct|interface|enum|mixin|extension|trait|type|def|func|function"
    r"|fun|fn|object|protocol)\s+{name}\b"
)
WEAK_DEFINITION = r"\b(val|var|let|const|final|static)\b[^\n]*\b{name}\b"


def find_definition(name, entries, strong_only=False):
    """Return the index chunk that defines `name`, or None.
    Try strong definitions first, then weak ones."""
    templates = (STRONG_DEFINITION,) if strong_only else (STRONG_DEFINITION, WEAK_DEFINITION)
    for template in templates:
        pattern = re.compile(template.format(name=re.escape(name)))
        for entry in entries:
            if pattern.search(entry["content"]):
                return entry
    return None


# Import-style lines across languages: import, from, using, use, require, #include
IMPORT_LINE = re.compile(r"^\s*(import|from|using|use|#include|require)\b.*$|^.*\brequire\(.*$", re.MULTILINE)


def import_lines(path, entries):
    """The import lines of a file (from its first chunk). Tells the model
    exactly what to import, even for names from external packages."""
    for entry in entries:
        if entry["path"] == path and entry["chunk"] == 0:
            return [m.group(0).strip() for m in IMPORT_LINE.finditer(entry["content"])]
    return []


def lookup_node(state):
    """After a failed verify: find the names in the error and look them up
    in the index. Gives the model FACTS instead of letting it guess again."""
    # 'quoted' / "quoted" / `quoted` identifiers, plus Go-style "undefined: x"
    names = set(re.findall(r"['\"`]([A-Za-z_]\w*)['\"`]", state["errors"]))
    names |= set(re.findall(r"undefined:\s*([A-Za-z_]\w*)", state["errors"]))
    names -= NOT_SYMBOLS

    facts = []
    # Names DEFINED in the file being edited (e.g. a method the model just
    # added twice) are known to the model — looking them up in the older
    # index would wrongly report "not in project". Only *used* names stay.
    edited = [{"content": state.get("new_content", "")}]
    names = {n for n in names if not find_definition(n, edited, strong_only=True)}

    for name in sorted(names)[:5]:
        e = find_definition(name, state["index"]["entries"])
        if e:
            # Keep facts SHORT and unambiguous. An earlier version pasted the
            # other file's code + imports, and the 7B model got confused and
            # tried to edit THAT file's lines. One clear sentence works better.
            imports = [i for i in import_lines(e["path"], state["index"]["entries"])
                       if name.lower() in i.lower() or "package:" in i or "from " in i]
            fact = f"`{name}` is defined in {e['path']}. Add an import for it in the same style as the existing imports."
            if imports and not re.search(STRONG_DEFINITION.format(name=re.escape(name)), e["content"]):
                # Name comes from a package: show how another file imports it.
                fact = (f"`{name}` comes from a package. {e['path']} uses it with one of "
                        f"these imports (copy the right one): " + "; ".join(imports[:6]))
            facts.append(fact)
            print(f"[lookup] {name} -> defined in {e['path']}")
        else:
            # Not in the project. It may still be real (a framework/SDK class
            # like Flutter's Navigator), or invented. Say exactly that.
            facts.append(
                f"`{name}` is NOT defined anywhere in this project. If it is a standard "
                f"framework/SDK name, import the right library. Otherwise stop using it: "
                f"define a placeholder for it in this file with a 'TODO:' comment."
            )
            print(f"[lookup] {name} -> not in project")
    return {"facts": "\n\n".join(facts)}


# ---------- 3. EDGES ----------
def after_generate(state):
    """If an edit block did not match the file, don't write/verify — ask the
    model again, telling it which SEARCH text was wrong."""
    if not state.get("edit_errors"):
        return "write"
    print(f"  edit problems:\n{indent(state['edit_errors'])}")
    if state["attempts"] < config.MAX_ATTEMPTS:
        return "retry"
    print(f"\n[generate] edits still invalid after {config.MAX_ATTEMPTS} attempts — giving up")
    return "done"


def after_verify(state):
    """The decision that makes this an agent: stop, or loop back?"""
    if state["passed"] or state.get("verify_broken"):
        return "done"
    if state["attempts"] < config.MAX_ATTEMPTS:
        return "retry"
    print(f"\n[verify] still failing after {config.MAX_ATTEMPTS} attempts — giving up")
    return "done"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("plan", plan_node)
    graph.add_node("generate", generate_node)
    graph.add_node("write", write_node)
    graph.add_node("verify", verify_node)
    graph.add_node("lookup", lookup_node)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "plan")
    graph.add_edge("plan", "generate")
    graph.add_conditional_edges(
        "generate", after_generate, {"write": "write", "retry": "generate", "done": END}
    )
    graph.add_edge("write", "verify")
    graph.add_conditional_edges("verify", after_verify, {"retry": "lookup", "done": END})
    graph.add_edge("lookup", "generate")
    return graph.compile()


# ---------- helpers ----------
def indent(text):
    return "\n".join("    " + line for line in text.splitlines()[-30:])
