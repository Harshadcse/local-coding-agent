"""
editor.py — apply SEARCH/REPLACE edits instead of rewriting whole files.

The problem: asking a small model to return the COMPLETE file means it must
copy every existing line perfectly. It often doesn't — in a real run it
silently deleted working import lines.

The fix (used by Aider, Claude Code and others): the model returns ONLY the
parts it wants to change, as blocks like this:

    <<<<<<< SEARCH
    import 'dart:convert';
    =======
    import 'dart:convert';
    import 'package:get_it/get_it.dart';
    >>>>>>> REPLACE

SEARCH = exact lines that already exist in the file.
REPLACE = what those lines should become.
Anything not mentioned in a block cannot be touched. To ADD code, the model
searches for a nearby "anchor" line and replaces it with anchor + new code.
To create a NEW file, SEARCH is left empty.

Small models don't follow any format 100% of the time, so `apply_reply`
also accepts a whole file in a ``` block. Whatever format came back, the
DELETION GUARD then checks that no existing lines silently disappeared.
"""

import difflib
import textwrap
import re

EDIT_FORMAT_HELP = """Return your changes as one or more SEARCH/REPLACE blocks, exactly like this:

<<<<<<< SEARCH
(exact existing lines copied from the current file, including indentation)
=======
(what those lines should be replaced with)
>>>>>>> REPLACE

Example (generic — look at the REAL current file for your SEARCH lines):

<<<<<<< SEARCH
import 'existing_import';
=======
import 'existing_import';
import 'new_import';
>>>>>>> REPLACE

<<<<<<< SEARCH
  existingLastMethod() {
    ...last lines of it, copied exactly...
  }
=======
  existingLastMethod() {
    ...last lines of it, copied exactly...
  }

  newMethod() {
    ...
  }
>>>>>>> REPLACE

Rules:
- SEARCH must match the current file EXACTLY. Keep it short: 1-5 lines is best.
- To ADD code, SEARCH for a nearby existing line and put that line plus your new code in REPLACE.
- To add an import, SEARCH for an existing import line.
- For a brand new empty file, leave SEARCH empty.
- Never delete existing code unless the task requires it. No explanations."""

# More than this many existing lines removed = suspicious (for additive tasks).
MAX_REMOVED_LINES = 3

# Import-style lines in most languages. Removing one almost always breaks code.
IMPORT_LIKE = re.compile(r"^\s*(import|from|using|use|#include|require|package)\b")

# Tolerant on purpose: 5-9 marker chars, extra spaces, and a missing final
# ">>>>>>> REPLACE" (then the block ends at the next SEARCH, ``` or the end).
BLOCK = re.compile(
    r"<{5,9} ?SEARCH[ \t]*\n(.*?)\n?={5,9}[ \t]*\n(.*?)"
    r"(?:\n?>{5,9} ?REPLACE[ \t]*|\n(?=<{5,9} ?SEARCH)|\n?```|\Z)",
    re.DOTALL,
)


def apply_reply(current, reply, original=None, allow_deletions=False):
    """Turn a model reply into new file content. Returns (new_content, problems).

    `current` is what the edit is applied to (may include earlier attempts).
    `original` is the file before the agent touched it: the guards compare
    against THAT, so the model may freely undo its own earlier mistakes.

    1. SEARCH/REPLACE blocks  -> apply them (preferred)
    2. else a ``` code block  -> treat it as the whole new file
    3. then the deletion guard checks nothing important vanished"""
    edits = parse_edits(reply)
    if edits:
        new_content, problems = apply_edits(current, edits)
        if problems:
            return current, problems
    else:
        blocks = re.findall(r"```[\w+-]*\n(.*?)```", reply, re.DOTALL)
        if not blocks:
            return current, ["No SEARCH/REPLACE blocks or code block found. Use the exact format."]
        new_content = max(blocks, key=len).rstrip() + "\n"

    if re.search(r"^(<{7}|={7}|>{7})", new_content, re.MULTILINE):
        return current, ["Edit markers (<<<<<<< / ======= / >>>>>>>) leaked into the code. "
                         "Use the exact block format."]
    baseline = current if original is None else original
    deleted = [] if allow_deletions else deletion_guard(baseline, new_content)
    return new_content, deleted + duplication_guard(baseline, new_content)


def duplication_guard(before, after):
    """Refuse changes that copy existing code a second time (e.g. the model
    pasted the whole class inside a method). Counts meaningful lines
    (> 15 chars) that now appear MORE often than before."""
    def counts(text):
        c = {}
        for line in text.splitlines():
            s = line.strip()
            if len(s) > 15:
                c[s] = c.get(s, 0) + 1
        return c

    old, new = counts(before), counts(after)
    duplicated = [line for line, n in new.items() if line in old and n > old[line]]
    if len(duplicated) > MAX_REMOVED_LINES:
        return ["Your change DUPLICATED existing code (these lines now appear twice). "
                "Only add the new code:\n" + "\n".join(duplicated[:15])]
    return []


def deletion_guard(before, after):
    """Refuse changes that silently drop existing code.
    Returns a list of problems (empty = OK)."""
    after_lines = {l.strip() for l in after.splitlines()}
    removed = [l.strip() for l in before.splitlines()
               if l.strip() and l.strip() not in after_lines]
    removed_imports = [l for l in removed if IMPORT_LIKE.match(l)]
    if removed_imports or len(removed) > MAX_REMOVED_LINES:
        return [
            "Your change REMOVED these existing lines. Keep them unless the task "
            "explicitly asks to delete them:\n" + "\n".join(removed[:30])
        ]
    return []


def parse_edits(reply):
    """Return a list of (search, replace) pairs found in the model's reply."""
    return BLOCK.findall(reply)


def apply_edits(content, edits):
    """Apply edits one by one. Returns (new_content, errors).
    errors is a list of messages for blocks that could not be applied —
    these go back to the model, just like analyzer errors."""
    errors = []
    for search, replace in edits:
        if not search.strip():                 # new file / empty file
            if content.strip():
                errors.append("A block had an empty SEARCH but the file is not empty.")
            else:
                content = replace + "\n"
            continue

        pos = find_at_line_start(content, search)
        if pos is not None:                    # 1. exact match (normal case)
            end = pos + len(search)
            if not replace and content[end:end + 1] == "\n":
                end += 1  # deleting whole lines: don't leave an empty line behind
            content = content[:pos] + replace + content[end:]
            continue

        fixed = replace_ignoring_whitespace(content, search, replace)
        if fixed is not None:                  # 2. match ignoring indentation
            content = fixed
            continue

        fixed = replace_fuzzy(content, search, replace)
        if fixed is not None:                  # 3. near-identical (e.g. 1 line missing)
            content = fixed
            continue

        errors.append(
            "This SEARCH text was not found in the file (it must match existing "
            f"lines exactly):\n{search}"
        )
    return content, errors


def find_at_line_start(content, search):
    """Position of `search` in `content`, but only where it starts at the
    beginning of a line. Otherwise "void f()" would match in the MIDDLE of
    "  void f()" and the replacement would double the indentation."""
    pos = content.find(search)
    while pos != -1:
        if pos == 0 or content[pos - 1] == "\n":
            return pos
        pos = content.find(search, pos + 1)
    return None


FUZZY_MIN_SIMILARITY = 0.85


def replace_fuzzy(content, search, replace):
    """Last resort: the model often copies a SEARCH block *almost* right
    (forgets one line, changes a comment). Slide a window over the file,
    and accept the most similar region if it is >= 85% similar AND clearly
    better than any other region. Otherwise refuse — a wrong guess would
    edit the wrong place."""
    lines = content.splitlines()
    wanted = "\n".join(l.strip() for l in search.strip("\n").splitlines())
    n = len(search.strip("\n").splitlines())
    if n < 2:  # too short to match safely by similarity
        return None

    candidates = []
    for size in (n - 1, n, n + 1):             # allow one line missing/extra
        for i in range(0, len(lines) - size + 1):
            window = "\n".join(l.strip() for l in lines[i:i + size])
            ratio = difflib.SequenceMatcher(None, wanted, window).ratio()
            candidates.append((ratio, i, size))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best_ratio, i, size = candidates[0]
    # "clearly better": other good matches must not overlap-compete elsewhere
    rivals = [c for c in candidates[1:] if c[0] >= best_ratio - 0.05 and abs(c[1] - i) > n]
    if best_ratio < FUZZY_MIN_SIMILARITY or rivals:
        return None
    new_lines = lines[:i] + replace.splitlines() + lines[i + size:]
    return "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")


def replace_ignoring_whitespace(content, search, replace):
    """Small models often get indentation slightly wrong. Compare lines with
    leading/trailing spaces removed; if exactly one place matches, use it."""
    lines = content.splitlines()
    wanted = [l.strip() for l in search.strip("\n").splitlines()]
    n = len(wanted)
    matches = [
        i for i in range(len(lines) - n + 1)
        if [l.strip() for l in lines[i:i + n]] == wanted
    ]
    if len(matches) != 1:  # none, or ambiguous -> refuse rather than guess
        return None
    i = matches[0]
    new_lines = lines[:i] + replace.splitlines() + lines[i + n:]
    return "\n".join(new_lines) + ("\n" if content.endswith("\n") else "")


# =====================================================================
# "add" mode — the model only says WHAT to add; this code decides WHERE.
# =====================================================================
# Why: a 7B model writes decent new code when asked for "just the new
# method", but fails often when it must ALSO copy SEARCH lines exactly,
# place the code, and manage imports. So we split the job:
#   model:   PLACE (which class), IMPORTS, CODE
#   program: dedupe imports, find the class end, fix indentation, insert.

ADD_FORMAT_HELP = """Reply in EXACTLY this format and nothing else:

PLACE: <name of the class the code belongs in, or FILE for top level>
IMPORTS:
```
<only import lines the new code needs that are NOT already in the file; leave empty if none>
```
CODE:
```
<only the NEW code to add — do not repeat existing code>
```"""

CLASS_LINE = r"^(\s*).*\b(class|struct|interface|object|impl|enum|extension|mixin)\s+{name}\b"


def parse_add_reply(reply):
    """Return (place, imports, code) or None if the reply has no code."""
    place = re.search(r"PLACE:\s*`?([\w.]+)`?", reply)
    imports = re.search(r"IMPORTS:\s*```[\w+-]*\n(.*?)```", reply, re.DOTALL)
    code = re.search(r"CODE:\s*```[\w+-]*\n(.*?)```", reply, re.DOTALL)
    if not code:  # tolerate a reply that is just one code block
        blocks = re.findall(r"```[\w+-]*\n(.*?)```", reply, re.DOTALL)
        if not blocks:
            return None
        code_text = max(blocks, key=len)
    else:
        code_text = code.group(1)
    return (
        place.group(1) if place else "FILE",
        imports.group(1) if imports else "",
        code_text,
    )


def apply_add(content, reply):
    """Insert the model's new imports + code. Returns (new_content, problems)."""
    parsed = parse_add_reply(reply)
    if not parsed:
        return content, ["No CODE block found. Reply in the exact PLACE/IMPORTS/CODE format."]
    place, import_text, code = parsed
    if not code.strip():
        return content, ["The CODE block is empty."]

    lines = content.splitlines()

    # 1. Code: find where it goes, then match the indentation there.
    insert_at, indent = find_insert_point(lines, place)
    body = textwrap.dedent(code).strip("\n").splitlines()
    new_code = [""] + [(indent + l) if l.strip() else "" for l in body]
    lines[insert_at:insert_at] = new_code

    # 2. Imports: after the last existing import, skipping duplicates.
    existing = {l.strip() for l in lines}
    new_imports = [l.strip() for l in import_text.splitlines()
                   if l.strip() and l.strip() not in existing and IMPORT_LIKE.match(l)]
    if new_imports:
        last = max((i for i, l in enumerate(lines) if IMPORT_LIKE.match(l)), default=-1)
        lines[last + 1:last + 1] = new_imports

    new_content = "\n".join(lines) + "\n"
    return new_content, duplication_guard(content, new_content)


def find_insert_point(lines, place):
    """Return (line index to insert at, indentation for the new code)."""
    if place and place.upper() != "FILE":
        pattern = re.compile(CLASS_LINE.format(name=re.escape(place)))
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if not m:
                continue
            class_indent = m.group(1)
            if "{" in "".join(lines[i:i + 3]):   # brace language
                end = matching_brace_line(lines, i)
                if end is not None:
                    return end, member_indent(lines[i + 1:end], class_indent + "  ")
            else:                                  # indentation language (Python)
                end = i + 1
                while end < len(lines) and (not lines[end].strip() or
                                            len(lines[end]) - len(lines[end].lstrip()) > len(class_indent)):
                    end += 1
                while end > i + 1 and not lines[end - 1].strip():
                    end -= 1                       # keep trailing blank lines after
                return end, member_indent(lines[i + 1:end], class_indent + "    ")
    # FILE (or class not found): append at the end of the file.
    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    return end, ""


def matching_brace_line(lines, start):
    """Line index of the '}' that closes the first '{' at/after `start`.
    Simple counter; good enough for normal code (ignores braces in strings)."""
    depth, opened = 0, False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth, opened = depth + 1, True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return i
    return None


def member_indent(body_lines, default):
    """Indentation used by the existing members of the class."""
    for l in body_lines:
        if l.strip():
            return l[: len(l) - len(l.lstrip())]
    return default
