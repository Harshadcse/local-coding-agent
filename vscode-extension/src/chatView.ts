// chatView.ts — the sidebar chat panel (like Copilot Chat / Claude).
//
// A webview is a small web page inside VS Code. The page and the extension
// can't call each other directly; they exchange messages:
//   page  --postMessage({type:"send"})-->  extension  --HTTP-->  Python server
//   page  <--postMessage({type:"entry"})-- extension  <--------
//
// The EXTENSION owns the chat history (a list of entries saved in
// workspaceState); the page only draws it. So the conversation survives
// switching to another sidebar view, closing the panel, or reloading VS Code.
//
// Features:
//   - Mode:  Ask    = answer in chat (the open file is sent as context)
//            Edit   = the agent changes the open file and a PROPOSAL CARD
//                     appears in the chat: diff + Accept / Reject / View diff
//            Review = review the open file against the context files (e.g.
//                     coding_standard.md): findings list + "Fix these"
//   - "@ Context": pick project files (standards, docs, related code) that are
//     sent with every Ask / Edit / Review until removed (like Claude's @-files)
//   - Model dropdown: installed Ollama models; "+ Install model..." downloads one
//   - Start/Stop server, indexing progress, Stop a running request, clickable
//     sources, Clear history
import * as vscode from "vscode";
import * as path from "path";
import { api, ContextFile, findProjectRoot, Finding, Health, projectPath } from "./api";
import { applyProposal, proposalProblem, proposalStatus, showProposalDiff } from "./proposals";

const MAX_CONTEXT_BYTES = 200_000; // larger open files are not sent as Ask context
const MAX_HISTORY = 100; // entries kept in workspaceState
const HISTORY_KEY = "localAgent.chatHistory";
const CONTEXT_KEY = "localAgent.contextFiles";
// Folders never offered in the "@ Context" picker.
const CONTEXT_EXCLUDE = "**/{node_modules,build,dist,out,.git,.dart_tool,Pods,.gradle,venv,.venv,__pycache__,.next,coverage}/**";
const SUGGESTED_MODELS = [
  { label: "qwen2.5-coder:7b", description: "4.7 GB · best all-round for code (default)" },
  { label: "qwen2.5-coder:3b", description: "1.9 GB · faster, weaker" },
  { label: "qwen2.5-coder:14b", description: "9 GB · stronger, slower, needs most of 16 GB RAM" },
  { label: "llama3.2:3b", description: "2 GB · small general model" },
  { label: "llama3.1:8b", description: "4.9 GB · general model" },
  { label: "deepseek-coder-v2:16b", description: "8.9 GB · strong code model, slow on 16 GB" },
];

type Source = { path: string; start_line: number };
type Entry =
  | { id: number; kind: "user"; text: string; mode: "ask" | "edit" | "review" }
  | { id: number; kind: "review"; file: string; uri: string; findings: Finding[]; context: string[]; fixed?: boolean }
  | { id: number; kind: "bot"; text: string; sources?: Source[] }
  | { id: number; kind: "error" | "note"; text: string }
  | {
      id: number; kind: "proposal"; file: string; uri: string; original: string; newContent: string;
      diff: string; status: string; todos: string[]; passed?: boolean;
      state: "pending" | "accepted" | "rejected" | "stale";
    };

export class ChatViewProvider implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private history: Entry[];
  private nextId: number;
  private running?: AbortController; // lets the Stop button cancel the request
  private busyText?: string;
  private serverUp = false;
  private contextFiles: vscode.Uri[]; // "@ Context" files, kept per workspace

  constructor(private context: vscode.ExtensionContext) {
    this.history = context.workspaceState.get<Entry[]>(HISTORY_KEY, []);
    this.nextId = Math.max(0, ...this.history.map((e) => e.id)) + 1;
    this.contextFiles = context.workspaceState.get<string[]>(CONTEXT_KEY, []).map((u) => vscode.Uri.parse(u));
  }

  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view;
    this.serverUp = false; // re-send models when the new page reports the server state
    view.webview.options = { enableScripts: true };
    view.webview.html = html();
    view.webview.onDidReceiveMessage((msg) => this.onMessage(msg));

    // Keep Start/Stop + model list in sync with the real server state.
    const timer = setInterval(() => this.sendServerState(), 5_000);
    view.onDidDispose(() => {
      clearInterval(timer);
      this.view = undefined;
    });
  }

  private async onMessage(msg: any) {
    switch (msg.type) {
      case "ready": // page loaded: draw the saved conversation + current state
        this.post({ type: "restore", entries: this.history });
        if (this.busyText) this.post({ type: "busy", on: true, text: this.busyText });
        this.sendContext();
        return this.sendServerState();
      case "send":
        if (msg.mode === "edit") return this.edit(msg.text);
        if (msg.mode === "review") return this.review(msg.text);
        return this.ask(msg.text);
      case "addContext":
        return this.pickContext();
      case "removeContext":
        this.contextFiles = this.contextFiles.filter((u) => u.toString() !== msg.uri);
        return this.saveContext();
      case "fixFindings":
        return this.fixFindings(msg.id);
      case "openUri":
        return openAt(vscode.Uri.parse(msg.uri), msg.line);
      case "stop":
        // 1) stop waiting in VS Code, 2) tell the server to stop the agent
        //    (it stops after its current step and restores the file).
        this.running?.abort();
        api.cancel().catch(() => undefined);
        return;
      case "clear":
        this.history = [];
        this.save();
        return this.post({ type: "restore", entries: [] });
      case "viewDiff":
        return this.viewDiff(msg.id);
      case "accept":
        return this.accept(msg.id);
      case "reject":
        return this.setProposalState(msg.id, "rejected");
      case "setModel":
        return this.setModel(msg.name);
      case "installModel":
        return this.installModel();
      case "startServer":
        await vscode.commands.executeCommand("localAgent.startServer");
        return this.sendServerState();
      case "stopServer":
        await vscode.commands.executeCommand("localAgent.stopServer");
        return setTimeout(() => this.sendServerState(), 700);
      case "open":
        return openSource(msg.path, msg.line);
    }
  }

  // ---------- Ask mode ----------
  private async ask(question: string) {
    this.add({ kind: "user", text: question, mode: "ask" });
    await this.run("Thinking... (searching the project, then asking the local model)", async (signal) => {
      // Like Copilot: the open file is part of the question's context, and its
      // project is the one searched (switches project / starts indexing if new).
      const files = await this.readContext();
      const open = activeFile();
      if (open) {
        const file = await projectPath(open);
        const doc = await vscode.workspace.openTextDocument(open);
        if (doc.getText().length <= MAX_CONTEXT_BYTES) files.push({ path: file, content: doc.getText() });
      }
      const r = await api.ask(question, files, signal);
      this.add({ kind: "bot", text: r.answer, sources: r.sources });
    });
  }

  // ---------- Edit mode: the agent proposes a change, shown as a card ----------
  private async edit(task: string, label?: string) {
    this.add({ kind: "user", text: label ?? task, mode: "edit" });
    const target = activeFile();
    if (!target) {
      this.add({ kind: "error", text: "Edit mode changes the open file: open one in the editor first." });
      return;
    }
    await this.run("Agent is working... (usually 15 s – 3 min)", async (signal) => {
      const file = await projectPath(target); // relative to the project
      const doc = await vscode.workspace.openTextDocument(target);
      if (doc.isDirty) await doc.save(); // the server reads the file from disk
      this.setBusy(`Agent is editing ${file}... (usually 15 s – 3 min)`);
      const original = doc.getText();
      const p = await api.doTask(task, file, signal, await this.readContext());

      const problem = proposalProblem(original, p);
      if (problem) {
        this.add({ kind: "note", text: problem });
        return;
      }
      this.add({
        kind: "proposal", file: p.file, uri: target.toString(), original, newContent: p.new_content,
        diff: p.diff, status: proposalStatus(p), todos: p.todos, passed: p.passed, state: "pending",
      });
      await showProposalDiff(target, p.file, p.new_content); // side-by-side view too
    });
  }

  // ---------- Review mode: findings against the context files ----------
  private async review(focus: string) {
    const target = activeFile();
    const names = this.contextFiles.map((u) => path.basename(u.fsPath));
    this.add({
      kind: "user", mode: "review",
      text: (focus || "Review this file") + (names.length ? `  (against ${names.join(", ")})` : ""),
    });
    if (!target) {
      this.add({ kind: "error", text: "Review mode reviews the open file: open one in the editor first." });
      return;
    }
    if (!names.length) {
      this.add({ kind: "note", text: "Tip: add your coding standards with “@ Context” to review against them. Using general best practices." });
    }
    await this.run("Reviewing... (usually 20–60 s)", async (signal) => {
      const file = await projectPath(target);
      const doc = await vscode.workspace.openTextDocument(target);
      if (doc.isDirty) await doc.save(); // the server reads the file from disk
      const r = await api.review(file, await this.readContext(), focus, signal);
      this.add({ kind: "review", file, uri: target.toString(), findings: r.findings, context: names });
    });
  }

  /** "Fix these" on a review card: run Edit with the findings as the task. */
  private async fixFindings(id: number) {
    const r = this.history.find((x) => x.id === id);
    if (r?.kind !== "review" || !r.findings.length) return;
    r.fixed = true;
    this.save();
    this.post({ type: "update", entry: r });
    const task = "Fix these code-review findings. Change only what is needed:\n" +
      r.findings.map((f) => `- line ${f.line} [${f.rule}]: ${f.problem} -> ${f.suggestion}`).join("\n");
    await vscode.window.showTextDocument(vscode.Uri.parse(r.uri), { preview: false }); // Edit targets the open file
    await this.edit(task, `Fix ${r.findings.length} review finding(s) in ${r.file}`);
  }

  // ---------- "@ Context" files ----------
  private async pickContext() {
    const open = activeFile();
    const root = open ? findProjectRoot(open.fsPath) : vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!root) {
      vscode.window.showWarningMessage("Open a project file first.");
      return;
    }
    const uris = await vscode.workspace.findFiles(new vscode.RelativePattern(root, "**/*"), CONTEXT_EXCLUDE, 5000);
    // Standards / guideline docs first, then other docs, then code.
    const rank = (u: vscode.Uri) => {
      const n = path.basename(u.fsPath).toLowerCase();
      if (/(standard|guideline|convention|rule|style|lint)/.test(n)) return 0;
      if (/\.(md|txt|rst|adoc)$/.test(n)) return 1;
      return 2;
    };
    const items = uris
      .map((u) => ({ uri: u, rank: rank(u), label: path.basename(u.fsPath), description: path.relative(root, u.fsPath) }))
      .sort((a, b) => a.rank - b.rank || a.description.localeCompare(b.description));
    const picked = await vscode.window.showQuickPick(items, {
      canPickMany: true,
      matchOnDescription: true,
      title: "Add context files (e.g. coding_standard.md) — type to search",
      placeHolder: "Standards and docs are listed first",
    });
    for (const p of picked ?? []) {
      if (!this.contextFiles.some((u) => u.toString() === p.uri.toString())) this.contextFiles.push(p.uri);
    }
    this.saveContext();
  }

  private async readContext(): Promise<ContextFile[]> {
    const files: ContextFile[] = [];
    for (const uri of this.contextFiles) {
      try {
        const bytes = await vscode.workspace.fs.readFile(uri);
        if (bytes.byteLength > MAX_CONTEXT_BYTES) continue;
        files.push({ path: vscode.workspace.asRelativePath(uri, false), content: Buffer.from(bytes).toString("utf8") });
      } catch {
        // file was deleted/moved: skip it
      }
    }
    return files;
  }

  private saveContext() {
    this.context.workspaceState.update(CONTEXT_KEY, this.contextFiles.map((u) => u.toString()));
    this.sendContext();
  }

  private sendContext() {
    this.post({
      type: "context",
      files: this.contextFiles.map((u) => ({ uri: u.toString(), name: path.basename(u.fsPath), full: vscode.workspace.asRelativePath(u, false) })),
    });
  }

  private proposal(id: number) {
    const e = this.history.find((x) => x.id === id);
    return e?.kind === "proposal" ? e : undefined;
  }

  private async viewDiff(id: number) {
    const p = this.proposal(id);
    if (p) await showProposalDiff(vscode.Uri.parse(p.uri), p.file, p.newContent);
  }

  private async accept(id: number) {
    const p = this.proposal(id);
    if (!p || p.state !== "pending") return;
    const uri = vscode.Uri.parse(p.uri);
    const current = (await vscode.workspace.openTextDocument(uri)).getText();
    // The file changed after the proposal was made: applying it would
    // overwrite those changes. Ask for a fresh proposal instead.
    if (current !== p.original) {
      this.setProposalState(id, "stale");
      this.add({ kind: "error", text: `${p.file} changed since this proposal was made. Send the request again for a fresh proposal.` });
      return;
    }
    await applyProposal(uri, p.newContent);
    this.setProposalState(id, "accepted");
  }

  private setProposalState(id: number, state: "accepted" | "rejected" | "stale") {
    const p = this.proposal(id);
    if (!p) return;
    p.state = state;
    this.save();
    this.post({ type: "update", entry: p });
  }

  /** Run a request with the busy indicator + Stop button; errors go to the chat. */
  private async run(text: string, work: (signal: AbortSignal) => Promise<void>) {
    this.running = new AbortController();
    this.setBusy(text);
    try {
      await work(this.running.signal);
    } catch (e) {
      this.add({ kind: "error", text: (e as Error).message });
    } finally {
      this.running = undefined;
      this.setBusy(undefined);
    }
  }

  private setBusy(text: string | undefined) {
    this.busyText = text;
    this.post({ type: "busy", on: !!text, text });
  }

  // ---------- history ----------
  private add(entry: any) {
    const e = { id: this.nextId++, ...entry } as Entry;
    this.history.push(e);
    this.save();
    this.post({ type: "entry", entry: e });
  }

  private save() {
    this.history = this.history.slice(-MAX_HISTORY);
    this.context.workspaceState.update(HISTORY_KEY, this.history);
  }

  // ---------- models ----------
  private async sendModels() {
    try {
      const m = await api.models();
      this.post({ type: "models", current: m.current, models: m.models });
    } catch {
      this.post({ type: "models", current: "", models: [] });
    }
  }

  private async setModel(name: string) {
    try {
      await api.setModel(name);
      // Remember the choice; it is re-applied whenever the server (re)starts.
      await vscode.workspace.getConfiguration("localAgent").update("model", name, vscode.ConfigurationTarget.Global);
      this.add({ kind: "note", text: `Model switched to ${name}.` });
    } catch (e) {
      this.add({ kind: "error", text: (e as Error).message });
    }
    this.sendModels();
  }

  private async installModel() {
    const pick = await vscode.window.showQuickPick(
      [...SUGGESTED_MODELS, { label: "Other...", description: "type any model name from ollama.com/library" }],
      { title: "Install an Ollama model (downloads once, then works offline)" }
    );
    this.sendModels(); // reset the dropdown away from "+ Install model..."
    if (!pick) return;
    let name: string | undefined = pick.label;
    if (name === "Other...") {
      name = await vscode.window.showInputBox({ prompt: "Model name", placeHolder: "e.g. phi3:mini, gemma2:9b" });
      if (!name) return;
    }
    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Downloading ${name} (can take several minutes)...` },
        () => api.pull(name!)
      );
      this.add({ kind: "note", text: `${name} installed.` });
      await this.setModel(name);
    } catch (e) {
      this.add({ kind: "error", text: `Install failed: ${(e as Error).message}` });
    }
  }

  // ---------- server state ----------
  private async sendServerState() {
    let up = false;
    let health: Health | undefined;
    try {
      health = await api.health();
      up = true;
    } catch {}
    if (up && !this.serverUp) {
      // Server just came up (or the page was re-created): re-apply the saved
      // model choice, then list models.
      const saved = vscode.workspace.getConfiguration("localAgent").get<string>("model", "");
      if (saved) await api.setModel(saved).catch(() => undefined);
      this.sendModels();
    }
    this.serverUp = up;
    this.post({ type: "server", up, indexing: indexingText(health) });
  }

  private post(msg: object) {
    this.view?.webview.postMessage(msg);
  }
}

/** "Indexing my_app… 45/213 files" while the server indexes in the background. */
function indexingText(h?: Health): string {
  const ix = h?.indexing;
  if (!ix || !ix.project) return "";
  const name = path.basename(ix.project);
  if (ix.state === "running") {
    return `Indexing ${name}… ${ix.done}/${ix.total || "?"} files — search across the project turns on when done`;
  }
  if (ix.state === "error") return `Indexing ${name} failed: ${ix.error}`;
  return "";
}

function activeFile(): vscode.Uri | undefined {
  // When the chat has focus, activeTextEditor can be empty: fall back to a visible editor.
  const editor = vscode.window.activeTextEditor ?? vscode.window.visibleTextEditors.find((e) => e.document.uri.scheme === "file");
  return editor?.document.uri.scheme === "file" ? editor.document.uri : undefined;
}

async function openAt(uri: vscode.Uri, line: number) {
  const doc = await vscode.workspace.openTextDocument(uri);
  const l = Math.max(line - 1, 0);
  await vscode.window.showTextDocument(doc, { selection: new vscode.Range(l, 0, l, 0), preview: false });
}

async function openSource(relPath: string, line: number) {
  // Source paths are relative to the indexed project, not the workspace.
  const project = (await api.health().catch(() => undefined))?.project;
  if (!project) return;
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(path.join(project, relPath)));
  const l = Math.max(line - 1, 0);
  await vscode.window.showTextDocument(doc, { selection: new vscode.Range(l, 0, l, 0) });
}

function html(): string {
  // Uses VS Code theme variables so it looks right in light and dark themes.
  return /* html */ `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 8px; }
  .bar { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--vscode-errorForeground); flex: none; }
  .dot.up { background: var(--vscode-testing-iconPassed, #3fb950); }
  .bar span { flex: 1; }
  .link { background: none; color: var(--vscode-textLink-foreground); padding: 2px 4px; }
  #log { display: flex; flex-direction: column; gap: 10px; margin-bottom: 10px; }
  .msg { padding: 8px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word; }
  .user { background: var(--vscode-input-background); align-self: flex-end; max-width: 90%; }
  .user.edit { border-left: 3px solid var(--vscode-textLink-foreground); }
  .bot { background: var(--vscode-editor-inactiveSelectionBackground); }
  .err { color: var(--vscode-errorForeground); }
  .note { opacity: 0.8; font-style: italic; }
  .src { font-size: 0.9em; opacity: 0.85; margin-top: 6px; }
  .src a { color: var(--vscode-textLink-foreground); cursor: pointer; display: block; }
  .card { border: 1px solid var(--vscode-panel-border, #444); border-radius: 6px; overflow: hidden; }
  .card .head { padding: 6px 8px; background: var(--vscode-editor-inactiveSelectionBackground); }
  .card .head b { word-break: break-all; }
  .card .status { font-size: 0.9em; opacity: 0.85; margin-top: 2px; }
  .card pre { margin: 0; padding: 6px 8px; max-height: 260px; overflow: auto; font-family: var(--vscode-editor-font-family);
              font-size: var(--vscode-editor-font-size); line-height: 1.35; white-space: pre; }
  .add { color: var(--vscode-gitDecoration-addedResourceForeground, #3fb950); background: rgba(63,185,80,0.10); display: block; }
  .del { color: var(--vscode-gitDecoration-deletedResourceForeground, #f85149); background: rgba(248,81,73,0.10); display: block; }
  .hunk { opacity: 0.6; display: block; }
  .card .todo { padding: 4px 8px; font-size: 0.9em; color: var(--vscode-editorWarning-foreground); }
  .card .actions { display: flex; gap: 6px; padding: 6px 8px; }
  .card .result { padding: 6px 8px; font-weight: bold; }
  .ok { color: var(--vscode-testing-iconPassed, #3fb950); }
  #indexing { font-size: 0.9em; opacity: 0.85; margin: -4px 0 8px; }
  #ctx { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px; }
  .chip { background: var(--vscode-badge-background); color: var(--vscode-badge-foreground);
          border-radius: 10px; padding: 2px 8px; font-size: 0.85em; }
  .chip b { cursor: pointer; margin-left: 4px; }
  .user.review { border-left: 3px solid var(--vscode-editorWarning-foreground); }
  .finding { padding: 6px 8px; border-top: 1px solid var(--vscode-panel-border, #444); }
  .finding .ln { color: var(--vscode-textLink-foreground); cursor: pointer; font-weight: bold; }
  .finding .rule { opacity: 0.75; }
  .finding .fix { margin-top: 2px; opacity: 0.9; }
  .finding code { display: block; margin-top: 2px; opacity: 0.7; font-family: var(--vscode-editor-font-family); white-space: pre-wrap; }
  textarea { width: 100%; box-sizing: border-box; min-height: 60px; background: var(--vscode-input-background);
             color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); padding: 6px; }
  select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
           border: 1px solid var(--vscode-dropdown-border, transparent); padding: 4px; min-width: 0; }
  .row { display: flex; gap: 6px; margin-top: 6px; align-items: center; }
  #model { flex: 1; }
  button { padding: 6px 10px; background: var(--vscode-button-background); color: var(--vscode-button-foreground);
           border: none; cursor: pointer; }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  button:disabled { opacity: 0.5; cursor: default; }
  #send, #stop { flex: 1; }
  .hidden { display: none; }
</style></head>
<body>
  <div class="bar">
    <div id="dot" class="dot"></div><span id="state">Server: checking...</span>
    <button id="start" class="secondary">Start</button>
    <button id="stopServer" class="secondary">Stop</button>
    <button id="clear" class="link" title="Clear chat history">Clear</button>
  </div>
  <div id="indexing" class="hidden"></div>
  <div id="log"></div>
  <div id="busy" class="msg bot note hidden"></div>
  <div id="ctx"></div>
  <textarea id="q" placeholder="Ask: How is login implemented?"></textarea>
  <div class="row">
    <select id="mode" title="Ask = answer in chat · Edit = change the file">
      <option value="ask">Ask</option>
      <option value="edit">Edit</option>
      <option value="review">Review</option>
    </select>
    <select id="model" title="Model used for answers and edits"><option>(server stopped)</option></select>
  </div>
  <div class="row">
    <button id="addctx" class="secondary" title="Add project files as context (e.g. coding_standard.md)">@ Context</button>
    <button id="send">Send (Cmd+Enter)</button>
    <button id="stop" class="hidden">■ Stop</button>
  </div>
<script>
  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);
  const log = $("log"), q = $("q"), send = $("send"), stop = $("stop"), mode = $("mode"), model = $("model");
  const WELCOME = "Ask about the project, Edit the open file, or Review it against your standards. Add files like coding_standard.md with “@ Context”. Runs 100% locally.";
  const nodes = new Map(); // entry id -> element

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---- draw one history entry ----
  function render(entry) {
    if (entry.kind === "user") {
      const icon = { edit: "✎ ", review: "🔍 " }[entry.mode] || "";
      return el("div", "msg user" + (entry.mode !== "ask" ? " " + entry.mode : ""), icon + entry.text);
    }
    if (entry.kind === "review") return renderReview(entry);
    if (entry.kind === "error") return el("div", "msg bot err", entry.text);
    if (entry.kind === "note") return el("div", "msg bot note", entry.text);
    if (entry.kind === "bot") {
      const div = el("div", "msg bot", entry.text);
      if (entry.sources && entry.sources.length) {
        const src = el("div", "src", "Sources:");
        entry.sources.forEach((s) => {
          const a = el("a", "", s.path + ":" + s.start_line);
          a.onclick = () => vscode.postMessage({ type: "open", path: s.path, line: s.start_line });
          src.appendChild(a);
        });
        div.appendChild(src);
      }
      return div;
    }
    if (entry.kind === "proposal") return renderProposal(entry);
    return el("div", "msg bot", JSON.stringify(entry));
  }

  // ---- inline proposal card: diff + Accept / Reject / View diff ----
  function renderProposal(p) {
    const card = el("div", "card");
    const head = el("div", "head");
    head.appendChild(el("div", "", "Proposed change to "));
    head.firstChild.appendChild(el("b", "", p.file));
    head.appendChild(el("div", "status", p.status));
    card.appendChild(head);

    const pre = el("pre");
    const lines = p.diff.split("\\n").filter((l) => !l.startsWith("---") && !l.startsWith("+++"));
    lines.slice(0, 120).forEach((l) => {
      const cls = l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "";
      pre.appendChild(el("span", cls, l + "\\n"));
    });
    if (lines.length > 120) pre.appendChild(el("span", "hunk", "... " + (lines.length - 120) + " more lines — use View diff\\n"));
    card.appendChild(pre);

    p.todos.forEach((t) => card.appendChild(el("div", "todo", "⚠ " + t)));
    if (p.passed === false && p.state === "pending") {
      card.appendChild(el("div", "todo err", "⚠ The checker still reports errors in this version. Reject and rephrase, or accept and ask for a fix."));
    }

    if (p.state === "pending") {
      const actions = el("div", "actions");
      const acc = el("button", p.passed === false ? "secondary" : "", p.passed === false ? "Accept anyway" : "✓ Accept");
      const rej = el("button", "secondary", "✗ Reject");
      const view = el("button", "secondary", "View diff");
      acc.onclick = () => vscode.postMessage({ type: "accept", id: p.id });
      rej.onclick = () => vscode.postMessage({ type: "reject", id: p.id });
      view.onclick = () => vscode.postMessage({ type: "viewDiff", id: p.id });
      [acc, rej, view].forEach((b) => actions.appendChild(b));
      card.appendChild(actions);
    } else {
      const text = { accepted: "✓ Applied — Cmd+Z in the editor to undo", rejected: "✗ Rejected — file unchanged",
                     stale: "File changed since this proposal — not applied" }[p.state];
      card.appendChild(el("div", "result" + (p.state === "accepted" ? " ok" : " err"), text));
    }
    return card;
  }

  // ---- review card: findings + "Fix these" ----
  function renderReview(r) {
    const card = el("div", "card");
    const head = el("div", "head");
    head.appendChild(el("div", "", "Review of "));
    head.firstChild.appendChild(el("b", "", r.file));
    head.appendChild(el("div", "status", r.findings.length + " finding(s)" +
      (r.context.length ? " · against " + r.context.join(", ") : " · general best practices")));
    card.appendChild(head);
    if (!r.findings.length) card.appendChild(el("div", "result ok", "✓ No problems found"));
    r.findings.forEach((f) => {
      const row = el("div", "finding");
      const ln = el("span", "ln", "Line " + f.line);
      ln.onclick = () => vscode.postMessage({ type: "openUri", uri: r.uri, line: f.line });
      row.appendChild(ln);
      row.appendChild(el("span", "rule", "  [" + f.rule + "]"));
      row.appendChild(el("div", "", f.problem));
      if (f.suggestion) row.appendChild(el("div", "fix", "→ " + f.suggestion));
      if (f.code) row.appendChild(el("code", "", f.code));
      card.appendChild(row);
    });
    if (r.findings.length) {
      const actions = el("div", "actions");
      const fix = el("button", "", r.fixed ? "Fix requested ↓" : "Fix these (" + r.findings.length + ")");
      fix.disabled = !!r.fixed;
      fix.onclick = () => vscode.postMessage({ type: "fixFindings", id: r.id });
      actions.appendChild(fix);
      card.appendChild(actions);
    }
    return card;
  }

  function addEntry(entry) {
    const node = render(entry);
    nodes.set(entry.id, node);
    log.appendChild(node);
    node.scrollIntoView();
  }

  function restore(entries) {
    log.innerHTML = "";
    nodes.clear();
    log.appendChild(el("div", "msg bot", WELCOME));
    entries.forEach(addEntry);
  }

  function busy(on, text) {
    send.classList.toggle("hidden", on);
    stop.classList.toggle("hidden", !on);
    $("busy").classList.toggle("hidden", !on);
    $("busy").textContent = text || "";
    if (on) $("busy").scrollIntoView();
  }

  function submit() {
    const text = q.value.trim();
    if (!stop.classList.contains("hidden")) return;
    if (!text && mode.value !== "review") return; // Review works without text
    q.value = "";
    vscode.postMessage({ type: "send", mode: mode.value, text });
  }

  send.onclick = submit;
  stop.onclick = () => vscode.postMessage({ type: "stop" });
  $("clear").onclick = () => vscode.postMessage({ type: "clear" });
  $("addctx").onclick = () => vscode.postMessage({ type: "addContext" });
  $("start").onclick = () => { $("state").textContent = "Server: starting..."; vscode.postMessage({ type: "startServer" }); };
  $("stopServer").onclick = () => vscode.postMessage({ type: "stopServer" });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(); });
  mode.onchange = () => {
    q.placeholder = {
      edit: "Edit: add try/catch around the API call in loginVerifyAsync",
      review: "Review the open file (optional focus, e.g. naming, error handling). Add standards with @ Context.",
      ask: "Ask: How is login implemented?",
    }[mode.value];
    vscode.setState({ mode: mode.value });
  };
  model.onchange = () => {
    if (model.value === "__install__") vscode.postMessage({ type: "installModel" });
    else vscode.postMessage({ type: "setModel", name: model.value });
  };

  window.addEventListener("message", (event) => {
    const msg = event.data;
    switch (msg.type) {
      case "restore": return restore(msg.entries);
      case "entry": return addEntry(msg.entry);
      case "update": {
        const old = nodes.get(msg.entry.id);
        const fresh = render(msg.entry);
        nodes.set(msg.entry.id, fresh);
        if (old) old.replaceWith(fresh);
        return;
      }
      case "busy": return busy(msg.on, msg.text);
      case "context": {
        const ctx = $("ctx");
        ctx.innerHTML = "";
        msg.files.forEach((f) => {
          const c = el("span", "chip", "@ " + f.name);
          c.title = f.full;
          const x = el("b", "", "×");
          x.title = "Remove";
          x.onclick = () => vscode.postMessage({ type: "removeContext", uri: f.uri });
          c.appendChild(x);
          ctx.appendChild(c);
        });
        return;
      }
      case "server":
        $("dot").classList.toggle("up", msg.up);
        $("state").textContent = msg.up ? "Server: running" : "Server: stopped";
        $("start").disabled = msg.up;
        $("stopServer").disabled = !msg.up;
        if (!msg.up) model.innerHTML = "<option>(server stopped)</option>";
        $("indexing").textContent = msg.indexing || "";
        $("indexing").classList.toggle("hidden", !msg.indexing);
        return;
      case "models": {
        model.innerHTML = "";
        msg.models.forEach((name) => {
          const o = el("option", "", name);
          o.value = name;
          o.selected = name === msg.current;
          model.appendChild(o);
        });
        const inst = el("option", "", "+ Install model...");
        inst.value = "__install__";
        model.appendChild(inst);
        return;
      }
    }
  });

  // Remember the selected mode across reloads of the page.
  const saved = vscode.getState();
  if (saved && saved.mode) { mode.value = saved.mode; mode.onchange(); }
  vscode.postMessage({ type: "ready" });
</script>
</body></html>`;
}
