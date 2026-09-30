# Demo Script (~10 minutes)

A walkthrough for presenting the Local Coding Agent to a team, using the
bundled `examples/demo_app`.

## Before the demo (5 minutes, do it early)

1. `./setup.sh` has run once, the `.vsix` is installed.
2. Start **Ollama** (app or `ollama serve`) and warm the model so the first
   answer isn't slow: `ollama run qwen2.5-coder:7b "hi"`.
3. Open `examples/demo_app` in VS Code, open the **Local Agent** chat,
   click **Start**. Wait until the header shows no "Indexing…" line.
4. Turn off Wi-Fi if you want to prove it is offline.
5. Reset the demo app if you ran it before: `git checkout -- examples/demo_app`.

## 1. The problem (1 min)

> "Copilot and Claude are great, but they send our code to the cloud. This
> runs a local model on this laptop — nothing leaves the machine. It works for
> any language. Let me show three things: Ask, Review, Edit."

Show the architecture diagram in the [README](../README.md).

## 2. Ask (2 min)

Open `lib/screens/login_screen.dart`. Mode **Ask**:

> *How does login work in this app?*

Point out: the answer follows the flow screen → `AuthService` → `ApiClient`,
and **Sources** link to the files (click one). Explain RAG in one sentence:
"it searches the project first, then answers from the code it found."

## 3. Review against our standard (3 min)

Open `lib/services/auth_service.dart`.

> "`dart analyze` says **No issues found** — but this file breaks our team's
> rules."

Run `dart analyze` in the terminal to show that. Then in the chat:

1. **@ Context** → pick `coding_standard.md` (a chip appears).
2. Mode **Review**, empty message, **Send**.

Point out the findings: abbreviations (`cnt`, `resp`, `usr`), `print()`,
the hard-coded key, missing try/catch — each with a clickable line and a fix.
Mention honestly: "a small model can report a false positive — that's why it
only *suggests*."

## 4. Fix with approval (3 min)

Click **Fix these** on the review card (or mode **Edit**:
*Replace print() with AppLogger.log()*).

While it runs: "it edits, runs `dart analyze`, and if there's an error it looks
up the right names in the project and retries."

When the proposal card appears:
- show the **diff** in the card and the side-by-side **View diff**,
- point at "✓ checker passed",
- click **Accept** — then **Cmd+Z** to show it's a normal undoable edit.

> "Nothing is ever written without approval."

## 5. Wrap-up (1 min)

- Works with any Ollama model — show the model dropdown / **+ Install model**.
- Any tech stack: the analyzer is auto-detected.
- How it's built: [HOW_IT_WORKS.md](HOW_IT_WORKS.md).
- Limits: a 7B local model is slower and weaker than cloud models; best for
  clear, specific tasks, reviews against a written standard, and private code.

## If something goes wrong

| Symptom | Fix |
|---|---|
| "Cannot reach the agent server" | click **Start** in the chat |
| First answer very slow | model was loading; warm it up (step 2 above) |
| Edit fails with "checker FAILED" | reject, make the request more specific, retry |
| Weird results after earlier runs | `git checkout -- examples/demo_app`, **Clear** the chat |
