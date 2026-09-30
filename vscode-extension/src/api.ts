// api.ts — the ONLY file that talks to the Python agent server (Phase 4).
// Same idea as llm.py on the Python side: one place for all network calls.
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

export interface Violation {
  source: string; // "linter" | "regex" | "llm"
  rule: string;
  line: number;
  reason: string;
}

export interface ContextFile {
  path: string;
  content: string;
}

export interface Finding {
  line: number;
  rule: string;
  problem: string;
  suggestion: string;
  code: string;
}

export interface Proposal {
  file: string;
  passed: boolean;
  attempts: number;
  diff: string;
  new_content: string;
  todos: string[];
  log: string;
}

function serverUrl(): string {
  return vscode.workspace.getConfiguration("localAgent").get("serverUrl", "http://localhost:8765");
}

async function call<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(serverUrl() + path, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new Error("Stopped.");
    throw new Error(
      `Cannot reach the agent server at ${serverUrl()}. Start it with: uvicorn agent.server:app --port 8765`
    );
  }
  const data = (await response.json()) as any;
  if (!response.ok) {
    throw new ApiError(data?.detail ?? `Server error ${response.status}`, response.status);
  }
  return data as T;
}

export interface Health {
  status: string;
  ollama: string;
  model: string;
  project: string | null;
  indexing: { project: string | null; state: "idle" | "running" | "done" | "error"; done: number; total: number; error: string | null };
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

// Files that mark a project root, for any tech stack. First match walking UP wins.
const ROOT_MARKERS = [
  "pubspec.yaml", "package.json", "go.mod", "Cargo.toml", "pyproject.toml",
  "requirements.txt", "pom.xml", "build.gradle", "composer.json", "Gemfile", ".git",
];

/** Nearest folder above `file` that contains a project marker. */
export function findProjectRoot(file: string): string {
  const workspaceRoot = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(file))?.uri.fsPath;
  let dir = path.dirname(file);
  while (true) {
    if (ROOT_MARKERS.some((m) => fs.existsSync(path.join(dir, m)))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir || dir === workspaceRoot) return workspaceRoot ?? dir;
    dir = parent;
  }
}

function inside(project: string, file: string): boolean {
  const rel = path.relative(project, file);
  return !!rel && !rel.startsWith("..") && !path.isAbsolute(rel);
}

/**
 * Path of `uri` relative to its project, as the server expects.
 * If the file belongs to a different project than the server's current one,
 * switch to it. A project that was never indexed starts indexing in the
 * background on the server; everything keeps working meanwhile.
 */
export async function projectPath(uri: vscode.Uri): Promise<string> {
  let project = (await api.health()).project;
  if (!project || !inside(project, uri.fsPath)) {
    project = (await api.switchProject(findProjectRoot(uri.fsPath))).project;
  }
  return path.relative(project, uri.fsPath).split(path.sep).join("/");
}

export const api = {
  health: () => call<Health>("/health"),
  ask: (question: string, files: { path: string; content: string }[] = [], signal?: AbortSignal) =>
    call<{ answer: string; sources: { path: string; start_line: number; end_line: number }[] }>(
      "/ask", { question, files }, signal),
  check: (file: string, use_llm: boolean) => call<{ violations: Violation[] }>("/check", { file, use_llm }),
  doTask: (task: string, file: string, signal?: AbortSignal, context: ContextFile[] = []) =>
    call<Proposal>("/do", { task, file, context }, signal),
  review: (file: string, context: ContextFile[], focus: string, signal?: AbortSignal) =>
    call<{ findings: Finding[] }>("/review", { file, context, focus }, signal),
  cancel: () => call<{ cancelled: boolean }>("/cancel", {}),
  switchProject: (project_path: string) => call<{ project: string; indexed: boolean }>("/project", { project_path }),
  models: () => call<{ current: string; models: string[] }>("/models"),
  setModel: (name: string) => call<{ current: string }>("/model", { name }),
  pull: (name: string) => call<{ installed: string }>("/pull", { name }),
  fix: (file: string, use_llm: boolean) =>
    call<{ violations: Violation[]; proposal: Proposal | null }>("/fix", { file, use_llm }),
};
