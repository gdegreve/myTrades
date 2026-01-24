# Claude Project Instructions

This repository is a Dash-based trading and portfolio management application.

Claude must follow these rules strictly when proposing or modifying code.

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
- `git checkout -b feat/<name>` (or `git switch -c feat/<name>`)
- `git branch --show-current` (confirm)

### 6.3 Merge-back workflow (ONLY after user confirmation)
Claude must **not** merge to `main` unless the user explicitly confirms the changes are correct and bug-free.

When the user asks to merge:
1. Ensure the working tree is clean:
   - `git status`
2. Pull latest `main` and rebase or merge (prefer rebase for linear history unless repo policy says otherwise):
   - `git fetch origin`
   - `git checkout main`
   - `git pull --ff-only`
   - `git checkout <feature-branch>`
   - `git rebase main` (or `git merge main` if requested)
3. Run/describe the relevant tests or smoke checks (as applicable).
4. Merge into `main`:
   - `git checkout main`
   - `git merge --no-ff <feature-branch>` (or fast-forward if repo policy allows)
5. Push:
   - `git push origin main`
6. Optional cleanup:
   - `git branch -d <feature-branch>`
   - `git push origin --delete <feature-branch>` (only if you want remote deletion)

Claude should present these as commands for the user to run, and should call out any conflicts/risk points.


---

## 7. How Claude should work

When asked to implement something:
1. Explain the approach briefly
2. Identify which files will change
3. Apply minimal changes
4. Warn about side effects or follow-up steps

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
