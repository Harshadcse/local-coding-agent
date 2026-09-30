// proposals.ts — show and apply the agent's proposed file content.
// Used by the right-click commands (notification) and the chat (inline card).
import * as vscode from "vscode";
import { Proposal } from "./api";

export const PROPOSAL_SCHEME = "local-agent-proposal";
const proposals = new Map<string, string>(); // proposal uri -> proposed content

/** Serves the proposed content to the diff editor (read-only, in memory). */
export const proposalProvider: vscode.TextDocumentContentProvider = {
  provideTextDocumentContent: (uri) => proposals.get(uri.toString()) ?? "",
};

/** Why a proposal can't be offered (empty or no change), or undefined if it's fine. */
export function proposalProblem(current: string, p: Proposal): string | undefined {
  // Safety net: never offer to replace a non-empty file with nothing.
  if (!p.new_content.trim() && current.trim()) {
    return "The agent returned an empty file — ignored. Nothing was changed.";
  }
  if (p.new_content === current) {
    return `The agent produced no change (checker ${p.passed ? "passed" : "failed"} after ${p.attempts} attempt(s)).`;
  }
  return undefined;
}

/** Open VS Code's diff editor: current file ↔ proposal (nothing is written). */
export async function showProposalDiff(uri: vscode.Uri, file: string, newContent: string) {
  const proposalUri = vscode.Uri.parse(`${PROPOSAL_SCHEME}:/${file}?${Date.now()}`);
  proposals.set(proposalUri.toString(), newContent);
  await vscode.commands.executeCommand("vscode.diff", uri, proposalUri, `${file} ↔ Agent proposal`);
}

/** Write the proposal into the file as a normal, undoable edit (Cmd+Z). */
export async function applyProposal(uri: vscode.Uri, newContent: string) {
  const doc = await vscode.workspace.openTextDocument(uri);
  const edit = new vscode.WorkspaceEdit();
  edit.replace(uri, new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length)), newContent);
  await vscode.workspace.applyEdit(edit);
  await doc.save();
  await vscode.window.showTextDocument(doc); // back from the diff to the edited file
}

export function proposalStatus(p: Proposal): string {
  const status = p.passed ? `✓ checker passed (attempt ${p.attempts})` : `✗ checker FAILED after ${p.attempts} attempts`;
  return status + (p.todos.length ? ` · ${p.todos.length} TODO(s) need your attention` : "");
}

