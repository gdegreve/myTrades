# Portfolio Module – Page Responsibilities

This document defines the **Portfolio domain structure** and the responsibility of each page.  
The goal is to clearly separate **intent, state, decision support, and execution**, following professional portfolio‑management principles.

---

## Portfolio → Overview
**Purpose:** Understand the current portfolio state at a glance.

**What belongs on this page**
- Total portfolio value and P/L
- Cash vs invested percentage
- Top positions and top sectors
- Performance versus benchmark(s)
- High‑level risk indicators (drawdown, volatility, exposure)

**Why it belongs here**
- Serves as the **entry point** for portfolio monitoring
- Answers: *“How am I doing right now?”*
- Read‑only by design: no editing, no rules, no actions

---

## Portfolio → Design (Requirements)
**Purpose:** Define portfolio intent and constraints.

**What belongs on this page**
- Target allocations (sector, region, asset type, themes)
- Minimum / maximum allocation bands
- Cash policy (minimum, target, maximum)
- Risk rules (max position size, max sector exposure, drawdown limits)
- Benchmark selection
- Rebalancing policy (when and how)

**Why it belongs here**
- Acts as the **source of truth** for the portfolio
- Everything else (signals, rebalance, alerts, AI) depends on it
- Separates **strategy and policy** from execution
- Prevents emotional or ad‑hoc trading decisions

> Think of this page as the **investment mandate**.

---

## Portfolio → Holdings
**Purpose:** Show the actual portfolio implementation.

**What belongs on this page**
- Current positions and cash
- Shares, cost basis, market value, P/L
- Sector and region classifications
- Data completeness indicators (missing sector, missing prices)

**Why it belongs here**
- Represents **reality**, not intent
- Used to detect drift versus Design rules
- Editing holdings belongs here, not in Overview
- Clean separation from policy and strategy logic

---

## Portfolio → Signals
**Purpose:** Provide decision support.

**What belongs on this page**
- Buy / sell / hold signals per holding
- Signal source (strategy, indicator, filter)
- Signal confidence or strength
- Conflicts with Design rules (e.g. sector limits reached)

**Why it belongs here**
- Signals are **advisory**, not execution
- Keeps strategy logic isolated and auditable
- Makes signal reasoning transparent
- Prevents silent or automatic actions

---

## Portfolio → Rebalance
**Purpose:** Convert intent into controlled action.

**What belongs on this page**
- Allocation drift versus targets
- Suggested trades to rebalance
- Cash usage preview
- Risk impact preview
- Simulation mode vs apply mode

**Why it belongs here**
- Rebalancing is an **explicit action**
- Must be reviewable and intentional
- Bridges Design and Holdings
- Avoids accidental or hidden trading

---

## Conceptual Flow
```
Design (intent)
   ↓
Holdings (reality)
   ↓
Signals (opportunities)
   ↓
Rebalance (execution)
   ↑
Overview (monitoring)
```

Each page has **one clear responsibility**.
No duplication. No ambiguity.

---

## One‑Line Summary
- **Overview** → How am I doing?
- **Design** → What am I allowed to do?
- **Holdings** → What do I own?
- **Signals** → What could I do?
- **Rebalance** → What will I do?

This structure matches how **professional portfolio‑management systems** are designed and scales cleanly as the application grows.

