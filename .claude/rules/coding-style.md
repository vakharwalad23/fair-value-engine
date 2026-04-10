# Coding Style Rules

## Commits
- Never add `Co-Authored-By: Claude` or any similar attribution line to commit messages.
- Instead add `Claude: <description of the change>` to the commit message body, if you want to indicate that a commit was generated with the help of Claude. This is for internal tracking purposes only and should not be included in the commit message header or as a co-author attribution.

## Comments
- Do not use decorative comment separators like `# ─────────────`, `# ═════════════`, `# ─── Section ───`, or similar box-drawing/repeated-character comment dividers in code.
- Use plain `#` comments only.

## Security
- Never read, cat, or open `.env` files. They contain secrets.

## Python
- Use `.venv` virtual environment for running tests and installing packages.
- Use `pytest` for testing.
