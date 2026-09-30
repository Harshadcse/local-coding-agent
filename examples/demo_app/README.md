# demo_app — sample project for the Local Coding Agent demo

A tiny Flutter app (login screen + services). It passes `dart analyze` with
**no issues**, yet it breaks the team's own rules in
[`coding_standard.md`](coding_standard.md) — exactly the kind of problems a
linter can't see, and the agent's **Review** mode can.

## Planted problems (for the presenter)

`lib/services/auth_service.dart`:

| Rule | Where |
|---|---|
| naming | `cnt`, `resp`, `usr` are abbreviations |
| no-print | `print('login attempt ...')` |
| no-secrets | `apiKey = "demo-key-..."` hard-coded (fake value) |
| error-handling | `login()` / `getProfile()` have no try/catch; `getProfile()` force-unwraps `resp!` |
| final-by-default | `var resp`, `var usr` are never reassigned |
| (duplication) | `'/auth/login'` hard-coded instead of `AppConfig.loginPath` |

`lib/services/api_client.dart`: network calls without try/catch.

## Reset after a demo

```bash
git checkout -- examples/demo_app
```
