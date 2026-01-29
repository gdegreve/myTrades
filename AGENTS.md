# AI Contribution Rules (Claude)

This repository uses AI-assisted development.
Claude (or any AI) MUST follow these rules.

---

## 0. Tool-Enabled Model Guardrails (MANDATORY when using local tool models)

### 0.1 No fake diffs / no invented file trees
- Do not generate diffs against non-existent Flask/Jinja structures.
- Never output placeholder git hashes.
- Every file path must be verified by `find`/`rg` before editing.

### 0.2 Mandatory “discover → edit → confirm” loop
For any implementation task:
1) DISCOVER:
   - `git rev-parse --show-toplevel`
   - `git branch --show-current`
   - `rg`/`find` to locate real files
2) EDIT:
   - apply real file edits via tools
3) CONFIRM:
   - `git status` must show modified/new files
   - show unified diff for only the touched files

If tool edits cannot be applied, STOP and ask for repo outputs or provide a unified diff only referencing real files.

### 0.3 Output rules
- Never output tool schema JSON (`TaskList`, `Glob`, etc.) as the final response.
- Deliver: unified diff + quick verification commands.

---

## 1. Architecture rules
- UI code lives ONLY in `app/pages/` or `app/components/`
- Business logic lives ONLY in `app/services/`
- Database access lives ONLY in `app/db/`
- Dash pages MUST NOT:
  - call yfinance directly
  - access sqlite directly
- External data (yfinance, APIs) must be:
  - in `services/`
  - cached
  - triggered only by explicit user actions

## 2. Dash rules
- No global state for data
- Use callbacks for updates
- No expensive computation in layout functions
- Use `dcc.Store` for lightweight UI state only

## 3. Code quality
- Code must pass:
  - black
  - ruff
  - pytest (if tests exist)
- No unused imports
- No commented-out code
- Functions must be small and named clearly

## 4. Scope discipline
- Modify ONLY the files explicitly requested
- Do NOT refactor unrelated files
- Do NOT invent new abstractions unless asked

## 5. Style
- Explicit, readable code > clever code
- Prefer clarity over brevity
