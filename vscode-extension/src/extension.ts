// extension.ts — entry point. VS Code calls activate() once when it starts.
//
// What we register:
//   - Commands (Command Palette + right-click menu): check, fix, change file, status
//   - Diagnostics: coding-standard violations shown as squiggles + Problems panel
//   - A proposal document provider: lets us show "current file vs agent's
//     proposal" in VS Code's built-in diff editor, BEFORE anything is written
//   - The sidebar chat view (chatView.ts)
import * as vscode from "vscode";
import { api, projectPath, Proposal, Violation } from "./api";
import { applyProposal, proposalProblem, proposalProvider, PROPOSAL_SCHEME, proposalStatus, showProposalDiff } from "./proposals";
import { ChatViewProvider } from "./chatView";
import { disposeServer, initServer, startServer, stopServer, toggleServer } from "./server";

let diagnostics: vscode.DiagnosticCollection;

export function activate(context: vscode.ExtensionContext) {
  diagnostics = vscode.languages.createDiagnosticCollection("localAgent");
  initServer(context);

  context.subscriptions.push(
    diagnostics,
    vscode.workspace.registerTextDocumentContentProvider(PROPOSAL_SCHEME, proposalProvider),
    // retainContextWhenHidden: keep the chat alive when another sidebar view is
    // shown (otherwise VS Code destroys it and the conversation is lost).
    vscode.window.registerWebviewViewProvider("localAgent.chat", new ChatViewProvider(context), {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand("localAgent.checkFile", checkFile),
    vscode.commands.registerCommand("localAgent.fixFile", fixFile),
    vscode.commands.registerCommand("localAgent.doTask", doTask),
    vscode.commands.registerCommand("localAgent.health", health),
    vscode.commands.registerCommand("localAgent.startServer", startServer),
    vscode.commands.registerCommand("localAgent.stopServer", stopServer),
    vscode.commands.registerCommand("localAgent.toggleServer", toggleServer)
  );
}

export function deactivate() {
  disposeServer();
}

// ---------- commands ----------

async function checkFile() {
  const doc = await activeSavedDocument();
  if (!doc) return;
  const file = await relativePath(doc);
  if (!file) return;
  const result = await withProgress(`Checking ${file}...`, () => api.check(file, useLlm()));
  showViolations(doc, result.violations);
  vscode.window.showInformationMessage(
    result.violations.length ? `${result.violations.length} coding-standard issue(s) found — see Problems panel.` : "No issues found."
  );
}

async function fixFile() {
  const doc = await activeSavedDocument();
  if (!doc) return;
  const file = await relativePath(doc);
  if (!file) return;
  const result = await withProgress(`Checking and fixing ${file} (can take a few minutes)...`, () =>
    api.fix(file, useLlm())
  );
  showViolations(doc, result.violations);
  if (!result.proposal) {
    vscode.window.showInformationMessage("No issues to fix.");
    return;
  }
  await reviewProposal(doc, result.proposal);
}

async function doTask() {
  const doc = await activeSavedDocument();
  if (!doc) return;
  const file = await relativePath(doc);
  if (!file) return;
  const task = await vscode.window.showInputBox({
    prompt: `What should the agent change in ${file}?`,
    placeHolder: "e.g. add a logout() method that sets isLogged to false",
  });
  if (!task) return;
  const proposal = await withProgress("Agent is working (can take a few minutes)...", () =>
    api.doTask(task, file)
  );
  await reviewProposal(doc, proposal);
}

async function health() {
  try {
    const h = await api.health();
    vscode.window.showInformationMessage(`Agent server OK · Ollama ${h.ollama} · ${h.model} · project ${h.project ?? "none"}`);
  } catch (e) {
    vscode.window.showErrorMessage(String((e as Error).message));
  }
}

// ---------- human in the loop (right-click commands): notification Accept / Reject ----------

async function reviewProposal(doc: vscode.TextDocument, p: Proposal): Promise<string> {
  const problem = proposalProblem(doc.getText(), p);
  if (problem) {
    vscode.window.showWarningMessage(problem);
    return problem;
  }
  await showProposalDiff(doc.uri, p.file, p.new_content);
  const status = proposalStatus(p);
  const choice = await vscode.window.showInformationMessage(`Agent proposal: ${status}. Apply it?`, "Accept", "Reject");
  if (choice === "Accept") {
    await applyProposal(doc.uri, p.new_content);
    vscode.window.showInformationMessage("Change applied (Cmd+Z to undo).");
    return `✓ Applied to ${p.file} — ${status}. Cmd+Z to undo.`;
  }
  vscode.window.showInformationMessage("Proposal rejected — file unchanged.");
  return `Rejected — ${p.file} unchanged (${status}).`;
}

// ---------- helpers ----------

function showViolations(doc: vscode.TextDocument, violations: Violation[]) {
  diagnostics.set(
    doc.uri,
    violations.map((v) => {
      const line = Math.min(Math.max(v.line - 1, 0), doc.lineCount - 1);
      const severity = v.source === "llm" ? vscode.DiagnosticSeverity.Information : vscode.DiagnosticSeverity.Warning;
      const d = new vscode.Diagnostic(doc.lineAt(line).range, `[${v.rule}] ${v.reason}`, severity);
      d.source = `Local Agent (${v.source})`;
      return d;
    })
  );
}

async function activeSavedDocument(): Promise<vscode.TextDocument | undefined> {
  const doc = vscode.window.activeTextEditor?.document;
  if (!doc) {
    vscode.window.showWarningMessage("Open a file first.");
    return undefined;
  }
  if (doc.isDirty) await doc.save(); // the server reads the file from disk
  return doc;
}

/** Path relative to the indexed project, or undefined (error already shown). */
async function relativePath(doc: vscode.TextDocument): Promise<string | undefined> {
  try {
    return await projectPath(doc.uri);
  } catch (e) {
    vscode.window.showErrorMessage(`Local Agent: ${(e as Error).message}`);
    return undefined;
  }
}

function useLlm(): boolean {
  return vscode.workspace.getConfiguration("localAgent").get("useLlmRules", true);
}

async function withProgress<T>(title: string, work: () => Promise<T>): Promise<T> {
  try {
    return await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title },
      work
    );
  } catch (e) {
    vscode.window.showErrorMessage(`Local Agent: ${(e as Error).message}`);
    throw e;
  }
}
