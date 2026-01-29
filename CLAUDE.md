# Claude Project Instructions

This repository is a Dash-based trading and portfolio management application.

Claude must follow these rules strictly when proposing or modifying code.

---

## 0. Tool-Model Execution Protocol (MANDATORY for Qwen-tools / local tool models)

### 0.1 Always ground yourself in the real repo (before any edit)
Before making ANY change, Claude must run (or instruct the user to run) commands to confirm:
- current working directory is the repo root
- real file structure
- routing/navigation implementation files

**Required grounding steps (in this order):**
1) `git rev-parse --show-toplevel`
2) `git branch --show-current`
3) `ls -la`
4) Identify relevant files using:
   - `rg -n "Rebalance|Holdings|Signals|pages|sidebar|nav|router" app || true`
   - `find app -maxdepth 3 -type f -name "*.py" | sort`

Claude must NOT invent paths. If unsure, Claude must ask to run `find/rg` and wait.

### 0.2 Editing behavior (tools must actually apply changes)
- Claude must prefer tool-based edits (apply patches / modify files) rather than “imaginary diffs”.
- Claude must not output tool schema JSON (e.g. `{"name": "Glob"}` / `{"name":"TaskList"}`) as the final answer.
- Output must be either:
  1) **Applied edits confirmed by `git status`**, plus a unified diff, OR
  2) If tool edits fail: a **unified diff only** that references **real existing files** (no placeholders).

### 0.3 Diff validity rules
- Never use placeholder hashes like `1234567..abcdef`.
- Never propose Flask/Jinja templates (`app/templates/*`) unless such folders exist in the repo (must be verified by `find`).
- All diffs must reference real files that exist OR explicitly marked NEW FILES under existing directories.

---

## 1. Architecture (NON-NEGOTIABLE)

### Separation of concerns
- `app/pages/`
  - Dash layouts
  - Dash callbacks
  - UI logic only
  - NO direct SQL
  - NO business logic
- `app/db/`
  - SQLite access
  - Repository-style functions only
  - One responsibility per function
- `app/assets/`
  - CSS only
- `app/main.py`
  - App bootstrap
  - Routing only

Violations of this structure are considered bugs.

---

## 2. Database rules

- SQLite database name is `trading.sqlite`
- DB access is ONLY via `app/db/*`
- Pages must NEVER import `sqlite3`
- All DB reads must be safe and read-only unless explicitly implementing a write step
- Writes must be transactional and validated

---

## 3. Portfolio domain model

Portfolio pages are strictly separated:

- **Overview** → read-only state & KPIs
- **Design** → portfolio intent & constraints
- **Holdings** → actual positions & cash
- **Signals** → decision support only (no execution)
- **Rebalance** → explicit action page

Claude must not mix responsibilities across these pages.

---

## 4. Dash callback rules

- One Output → one callback (unless `allow_duplicate=True` is explicitly justified)
- Avoid feedback loops
- Avoid dynamic component re-creation with stateful IDs
- Prefer small, deterministic callbacks
- Use `PreventUpdate` instead of returning unchanged values

---

## 5. UI & styling rules

- One font everywhere (defined in `assets/styles.css`)
- Pages must visually align with the sidebar design
- Prefer clarity over density
- No inline CSS unless explicitly requested
- No UI refactors unless asked

---

## 6. Git & workflow rules

### 6.1 Minimal change discipline
- Minimal diffs only
- Never touch unrelated files
- Never reformat code unless requested
- Respect `.gitignore`
- Do not generate or commit local state (`__pycache__`, SQLite, Claude cache)

### 6.2 Branch-first workflow (MANDATORY)
Claude must **never** implement changes directly on `main` (or `master`).

**Before making ANY code edits**, Claude must:
1. Check the current branch.
2. If on `main`/`master`, create and switch to a new branch using the naming strategy below.
3. Confirm the active branch name in the response.
4. Only then start editing files.

If any git command fails, Claude must **stop immediately** and report the error output.

#### Branch naming strategy
Use one of these prefixes:
- `feat/<short-description>` for new functionality
- `fix/<short-description>` for bug fixes
- `refactor/<short-description>` for code improvements without behavior change
- `chore/<short-description>` for maintenance (docs, tooling, small housekeeping)

Rules:
- `kebab-case` only (lowercase letters, numbers, dashes)
- 4–7 words max, descriptive, no dates
- Prefer domain-first naming (e.g., `feat/portfolio-benchmark-kpis`)

Examples:
- `fix/overview-kpi-refresh`
- `feat/signals-sector-breakdown`
- `refactor/db-repo-queries`
- `chore/update-claude-instructions`

#### Required git commands (example)
Claude should show commands like:
- `git status`
- `git branch --show-current`
- `git switch -c feat/<name>`
- `git branch --show-current` (confirm)

### 6.3 Merge-back workflow (ONLY after user confirmation)
Claude must **not** merge to `main` unless the user explicitly confirms the changes are correct and bug-free.

(keep your existing merge steps here)

---

## 7. How Claude should work

When asked to implement something:
1. Ground the repo (Section 0) if needed
2. Explain approach briefly
3. Identify which files will change (real paths only)
4. Apply minimal changes
5. Provide unified diff + `git status` confirmation

When debugging:
- Identify the root cause first
- Explain why the issue happens
- Propose the smallest correct fix

---

## 8. Out of scope (unless explicitly requested)

- Performance optimizations
- Large refactors
- New frameworks
- Styling redesigns
- AI/agent logic inside the app

---

## 9. Tone & assumptions

- Treat the user as a senior developer
- Prefer correctness over cleverness
- If unsure, ask before implementing
