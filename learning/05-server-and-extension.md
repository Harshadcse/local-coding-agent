# Phase 05 — Local Server + VS Code Extension

**Code:** `agent/server.py`, `vscode-extension/src/*.ts`

## The one-paragraph explanation

The VS Code extension is TypeScript and can't import Python, so the agent runs
as a small web server (FastAPI) on `localhost`. The extension is only UI — chat,
cards, squiggles — and forwards every request over HTTP. Still 100% offline:
the only network traffic is the laptop talking to itself.

```
VS Code ── extension (TypeScript) ──HTTP localhost:8765──► agent server (Python) ──► Ollama
```

## Key design decisions

1. **Proposals, not edits.** `/do` runs the agent, then *restores the file* and
   returns the new content + diff. The editor writes the file only when the
   user clicks Accept (as a normal, undoable edit). Human in the loop.
2. **One run at a time + cancel.** A lock prevents two runs editing files at
   once; `/cancel` stops the agent after its current step and restores the file.
3. **Paths relative to the project, not the editor workspace.** A workspace
   opened one folder too high sent `my_app/lib/...` — the server found no such
   file, treated it as empty, and the proposal looked like "delete every line".
   Fix: find the project root from the file (nearest `pubspec.yaml`,
   `package.json`, `.git`, …), and refuse missing files loudly.
4. **Index in the background.** The first use of a project starts indexing in
   a thread; everything works immediately with the open file as context, and
   project-wide search switches on when indexing finishes.
5. **The extension owns the chat history.** A webview is destroyed when
   hidden, so the extension keeps the conversation (saved per workspace) and
   redraws it.
6. **Review inside the chat.** Accept/Reject lives on a proposal card in the
   conversation, not in a pop-up notification.

## Webview basics

A webview is a small web page inside VS Code. The page and the extension can't
call each other directly — they exchange messages:

```
page  --postMessage({type: "send"})-->   extension  --HTTP-->  server
page  <--postMessage({type: "entry"})--  extension  <--------
```

## Files

| File | Job |
|---|---|
| `api.ts` | the only file that calls the server; project-root detection |
| `chatView.ts` | chat: history, Ask/Edit/Review, @ Context, cards, models |
| `proposals.ts` | diff editor view, apply as undoable edit |
| `server.ts` | start/stop the Python server, status bar |
| `extension.ts` | registration, right-click commands, squiggles |

## Try it

```bash
uvicorn agent.server:app --port 8765     # then open http://localhost:8765/docs
```
Or press **Start** in the chat panel. For extension development: open
`vscode-extension/` in VS Code and press **F5**.

## Check your understanding

- Why does the server restore the file instead of keeping the change?
- What happens if two `/do` requests arrive at once?
- Why can't the chat page simply `import` the API client?
- Why is "Accept" refused if the file changed after the proposal was made?
