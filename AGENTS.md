# AI Contribution Rules (Claude)

This repository uses AI-assisted development.
Claude (or any AI) MUST follow these rules.

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
