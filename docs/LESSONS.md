# Lessons: Building an Agent on a Small Local Model

Notes from building this project step by step (RAG → agent loop → safe edits
→ standards → server → VS Code extension). Most of the work was not "call the
LLM" — it was everything around the LLM that makes a 7B model usable.

## Retrieval

- **Naive RAG is fooled by keywords.** Plain cosine similarity ranked a
  translation JSON full of `login_*` keys above the real login code.
  Fixes that worked: put the file path in front of each chunk before
  embedding, down-rank data files, and add an LLM rerank stage.
- **Use the embedding model's prefixes** (`search_query:` /
  `search_document:` for nomic-embed-text).

## Editing

- **Whole-file rewrites lose code.** A small model asked to return the full
  file silently dropped working import lines. SEARCH/REPLACE edits make
  unrelated code untouchable.
- **Validate outputs, don't just constrain them.** No 7B model follows a
  format 100% of the time. Accept several formats, then check the *result*
  (deletion, duplication and marker guards).
- **Match leniently, but only where it's unambiguous.** Exact → indentation-
  tolerant → ≥85% similar *and* unique. A wrong guess edits the wrong place.
- **Code-specialised models matter.** Switching from a general 8B model to
  `qwen2.5-coder:7b` turned a failing edit into a clean 2-attempt pass.

## The retry loop

- **A retry only helps if the model gets new information.** Feeding back
  "`logoutUrl` isn't defined" three times produced the same invented name
  three times. Looking up what *does* exist and saying "X does not exist —
  don't use it" fixed it.
- **Short, focused repair prompts beat long ones.** Buried in a 5,000-token
  prompt, the model ignored the one error line; alone, it fixed it at once.
- **Once stuck, the model copies its own previous code.** Some errors (where
  the fix isn't stated in the message) needed a *fresh* attempt, not a repair.
- **Start every attempt from the original file**, or broken attempts stack up
  (a method got added twice).
- **Temperature 0 makes runs reproducible — and makes stuck loops repeat
  forever.** Use 0 for the first attempt, a little randomness for retries.
- **Environment errors are not code errors.** "command not found" must stop
  the loop, not trigger three rewrites of correct code.

## Prompts

- **More context is not always better.** Pasting another file's imports and
  code into a hint made the model try to edit *that* file.
- **Examples beat rules — including bad examples.** An example snippet shown
  without its surrounding class caused the model to paste it in the wrong
  place.
- **Vague tasks produce invented APIs.** "Add logout" (no logout endpoint
  exists) fails; "add logout() that clears the stored session like the
  settings page does" passes. When something is missing, ask for a `TODO`
  placeholder instead of a guess.

## Measuring

- **Measure, don't eyeball.** Judging changes by one or two runs fooled me
  several times. A small eval set (5 tasks × 2 runs, pass/fail with regex
  checks) showed SEARCH/REPLACE at 7/10 and "add only new code" at 6/10 but
  ~5× faster — a real trade-off instead of a feeling.

## Product / UX

- **Every edit is a proposal.** Diff + Accept/Reject, undoable, and the file
  is restored if anything crashes or the user presses Stop.
- **Paths are relative to the project, not the editor's workspace.** A wrong
  base path made the agent "edit" a non-existent (empty) file, which looked
  like it wanted to delete everything.
- **Index in the background.** Asking users to wait for indexing is a
  blocker; working immediately with the open file and switching on search
  when ready is not.
- **Reviews need evidence.** Requiring each finding to quote the code at its
  line cut a review from 26 noisy findings to 4, and from 2 minutes to 30 s.
