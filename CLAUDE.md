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

- Minimal diffs only
- Never touch unrelated files
- Never reformat code unless requested
- Respect `.gitignore`
- Do not generate or commit local state (`__pycache__`, SQLite, Claude cache)

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
