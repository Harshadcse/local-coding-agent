// server.ts — start / stop the Python agent server from inside VS Code.
//
// Start = run `<agentFolder>/venv/bin/uvicorn agent.server:app --port <port>`
// as a child process. Its output goes to the "Local Agent Server" output panel.
// A status bar item shows whether the server is up; click it to start/stop.
import * as vscode from "vscode";
import { ChildProcess, spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { api } from "./api";

let child: ChildProcess | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let running = false;

export function initServer(context: vscode.ExtensionContext) {
  output = vscode.window.createOutputChannel("Local Agent Server");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = "localAgent.toggleServer";
  statusItem.show();

  const timer = setInterval(refreshStatus, 10_000); // poll /health every 10 s
  context.subscriptions.push(output, statusItem, { dispose: () => clearInterval(timer) });
  refreshStatus();
}

export async function startServer() {
  if (await isUp()) {
    vscode.window.showInformationMessage("Agent server is already running.");
    return refreshStatus();
  }
  const folder = await agentFolder();
  if (!folder) return;

  const uvicorn = path.join(folder, "venv", "bin", "uvicorn");
  if (!fs.existsSync(uvicorn)) {
    vscode.window.showErrorMessage(`Not found: ${uvicorn}. Run 'pip install -r requirements.txt' in the venv.`);
    return;
  }
  const port = new URL(serverUrl()).port || "8765";
  output.appendLine(`> ${uvicorn} agent.server:app --port ${port}   (in ${folder})`);
  output.show(true);

  child = spawn(uvicorn, ["agent.server:app", "--port", port], { cwd: folder });
  child.stdout?.on("data", (d) => output.append(d.toString()));
  child.stderr?.on("data", (d) => output.append(d.toString())); // uvicorn logs to stderr
  child.on("exit", (code) => {
    output.appendLine(`[server exited with code ${code}]`);
    child = undefined;
    refreshStatus();
  });

  setStatus("starting");
  for (let i = 0; i < 20; i++) {             // wait up to ~10 s for /health
    await new Promise((r) => setTimeout(r, 500));
    if (await isUp()) {
      vscode.window.showInformationMessage("Agent server started.");
      return refreshStatus();
    }
  }
  vscode.window.showErrorMessage("Agent server did not start — see the 'Local Agent Server' output panel.");
  refreshStatus();
}

export async function stopServer() {
  if (child) {
    child.kill();
    child = undefined;
    vscode.window.showInformationMessage("Agent server stopped.");
  } else if (await isUp()) {
    vscode.window.showWarningMessage("The server was started outside VS Code — stop it in its terminal (Ctrl+C).");
  } else {
    vscode.window.showInformationMessage("Agent server is not running.");
  }
  setTimeout(refreshStatus, 500);
}

export async function toggleServer() {
  return running ? stopServer() : startServer();
}

export function disposeServer() {
  child?.kill(); // never leave an orphan server behind when VS Code closes
}

// ---------- helpers ----------

async function refreshStatus() {
  setStatus((await isUp()) ? "running" : "stopped");
}

function setStatus(state: "running" | "stopped" | "starting") {
  running = state === "running";
  statusItem.text = {
    running: "$(hubot) Agent: running",
    stopped: "$(circle-slash) Agent: stopped",
    starting: "$(sync~spin) Agent: starting",
  }[state];
  statusItem.tooltip = running ? "Click to stop the local agent server" : "Click to start the local agent server";
}

async function isUp(): Promise<boolean> {
  try {
    await api.health();
    return true;
  } catch {
    return false;
  }
}

function serverUrl(): string {
  return vscode.workspace.getConfiguration("localAgent").get("serverUrl", "http://localhost:8765");
}

/** The learn-agent folder (contains venv/ and agent/). Asked once, then saved in settings. */
async function agentFolder(): Promise<string | undefined> {
  const config = vscode.workspace.getConfiguration("localAgent");
  let folder = config.get<string>("agentFolder", "");
  if (folder && fs.existsSync(path.join(folder, "agent", "server.py"))) return folder;

  const picked = await vscode.window.showOpenDialog({
    canSelectFolders: true,
    canSelectFiles: false,
    openLabel: "Select the learn-agent folder",
    title: "Where is the agent (the folder with venv/ and agent/)?",
  });
  if (!picked?.[0]) return undefined;
  folder = picked[0].fsPath;
  if (!fs.existsSync(path.join(folder, "agent", "server.py"))) {
    vscode.window.showErrorMessage(`${folder} does not contain agent/server.py.`);
    return undefined;
  }
  await config.update("agentFolder", folder, vscode.ConfigurationTarget.Global);
  return folder;
}
