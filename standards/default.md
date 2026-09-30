# Coding standards (default checklist)

Each rule starts with `## <id>: <description>`.
Add a `pattern: <regex>` line to check a rule with a regex (fast, exact).
Rules WITHOUT a pattern are judged by the local LLM (slower, can be wrong).
Copy this file to `<your project>/.agent/standards.md` to customise it per project.

## no-secrets: No API keys, tokens or passwords hard-coded in source code.
pattern: (AIza[0-9A-Za-z_\-]{35}|(?i)(api_?key|secret|password|token)\s*[:=]\s*["'][^"']{8,}["'])

## no-print: Do not use print() for logging in app code; use the project's logger.
pattern: ^\s*print\(

## no-todo-left: No TODO comments left in finished code.
pattern: //\s*TODO|#\s*TODO

## service-no-ui: Service / data classes must not use UI code (BuildContext, Navigator, widgets, dialogs).

## handle-errors: Network / API calls should handle failures (null response, exceptions) instead of ignoring them.

## clear-names: Methods and variables have clear, descriptive names (no single letters except loop counters).
