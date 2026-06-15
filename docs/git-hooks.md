# Git Hooks

CodeGraph provides optional Git hooks for automated code impact analysis.

## Optional Git pre-commit impact hook

CodeGraph can install an optional backend-only pre-commit hook:

```bash
codegraph configure git-hook --pre-commit-impact
```

The hook checks staged changed files with:

```bash
codegraph workflow impact --files <staged files> --change-type unknown --format markdown
```

Default behavior:

- **warning only** — does not block commits
- does not run tests
- does not modify files
- does not install frontend/dashboard
- does not call external services

If you already have a pre-commit hook, CodeGraph will not overwrite it unless `--force` is used.

## Hook Script

The generated `.git/hooks/pre-commit` script:

```sh
#!/usr/bin/env sh
set -u

STAGED_FILES="$(git diff --cached --name-only --diff-filter=ACMR | tr '\n' ',' | sed 's/,$//')"

if [ -z "$STAGED_FILES" ]; then
  exit 0
fi

echo "[CodeGraph] Running pre-commit impact check..."
codegraph workflow impact --files "$STAGED_FILES" --change-type unknown --format markdown

STATUS=$?

if [ "$STATUS" -ne 0 ]; then
  echo "[CodeGraph] Impact check failed or index is unavailable."
  echo "[CodeGraph] Commit is not blocked by default."
  exit 0
fi

exit 0
```

Key properties:

- Always exits 0 (never blocks commits)
- Prints impact analysis to terminal
- If `codegraph workflow impact` is not installed, prints a warning but does not block
- Compatible with macOS, Linux, and Git Bash (Windows)
- Uses POSIX `sh` for maximum compatibility

## Installing

```bash
# In your Git repository root:
codegraph configure git-hook --pre-commit-impact
```

## Force Overwrite

If you already have a `.git/hooks/pre-commit` hook:

```bash
codegraph configure git-hook --pre-commit-impact --force
```

This will:
1. Back up the existing hook to `.git/hooks/pre-commit.codegraph.bak` (with timestamp if the backup already exists)
2. Install the CodeGraph pre-commit impact hook

## Manual Installation

If you prefer to merge the CodeGraph hook into your existing pre-commit hook manually, add the block above to your `.git/hooks/pre-commit` file. Make sure the file is executable:

```bash
chmod +x .git/hooks/pre-commit
```

## Removing

To remove the hook, simply delete `.git/hooks/pre-commit` or restore from the backup:

```bash
rm .git/hooks/pre-commit
# Or restore backup:
mv .git/hooks/pre-commit.codegraph.bak .git/hooks/pre-commit
```

## Saving Reports to a File

By default, the hook prints the Markdown report to the terminal. To save it to a file, you can run manually:

```bash
codegraph workflow impact --files src/server.ts --output .codegraph/reports/impact-report.md
```

The hook does not automatically write report files to avoid polluting the repository.

## Limitations

- **Not a test runner** — the hook does not run tests or modify code
- **Not a CI replacement** — it's an advisory tool for local development
- **Does not auto-init** — the hook does not run `codegraph init` or refresh the index
- **POSIX sh only** — Windows PowerShell hook is not yet supported
