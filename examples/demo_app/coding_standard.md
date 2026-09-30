# Team Coding Standard (demo)

## naming
Classes use PascalCase, variables and methods use camelCase. Names must be
descriptive — no abbreviations such as `usr`, `cnt`, `tmp`, `resp`.

## no-print
Never use `print()` for logging. Use `AppLogger.log()` from
`lib/services/app_logger.dart`.

## error-handling
Every network call must be wrapped in `try/catch`, must handle a `null` or
failed response, and must log the error with `AppLogger`.

## no-secrets
No API keys, tokens or passwords in source code. Read them from
`AppConfig` (which loads them from the environment).

## final-by-default
Use `final` for local variables that are never reassigned.

## small-methods
A method should do one thing and be at most ~30 lines.
