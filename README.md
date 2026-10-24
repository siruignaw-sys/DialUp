# Dial-Up

**The internet in a phone call.** Call a number, say what you need done online, and hang up.
An AI agent does the task in a real web browser, calls you back if it needs something only
you know, and calls you with the result. No app, no screen, no data plan.

Built at **c0mpiled-16 @ UC San Diego** (Oct 24, 2026) · Track: **Unsupervised**

> 3.1 billion people live within mobile internet coverage but don't use it (GSMA, 2024).
> Most of them can make a phone call. Dial-Up turns a phone call into a web agent that
> works on its own, and knows when to stop.

## How it works

```
 caller ──call──▶ Twilio ──▶ FastAPI server ──▶ task row (SQLite)
                                     │
                                     ▼
                     agent loop (Claude + Playwright browser)
                       │   one action per turn, logged as a step
                       ▼
                     supervisor checks every step ── stop? ──┐
                       │                                     │
          needs info? ─┴─▶ calls caller, asks, keeps going   │
                                                             ▼
                       callback: done / gave up / stopped (with a spoken summary)
```

1. You call and say a task ("hold me a seat on the cheapest bus to LA tomorrow").
2. The server creates a task and starts the agent in the background. You hang up.
3. The agent drives a real headless browser: search, read, click, type.
4. If it needs your name or a choice, it **calls you** to ask.
5. Before anything irreversible (booking, submitting), it **calls you to confirm** (press 1).
6. Every task ends with exactly one callback, in your language.

## Knowing when to stop (the Unsupervised part)

A separate supervisor checks the step log after every action. It uses measurable signals,
not the agent's own opinion, because the model doing the work is the one that loses track.

| Stop reason | Rule |
|---|---|
| `over_budget` | Stops **before** a step would cross the cost cap, reserving room for the next step and the spoken summary |
| `looping` | Same action on the same page 3+ times in the last 8 steps |
| `stuck` | No new information for 6 steps while bouncing between ≤2 pages (or 12 steps total) |
| `max_steps` / `timeout` | Hard caps. Time spent on the phone with the caller doesn't count |

The agent can also stop itself: `give_up` for login walls, CAPTCHAs and paywalls (it never
enters passwords or card numbers), and `finish` when done. Either way, the caller gets a
spoken explanation of what it found and why it stopped.

### Measured cost (Claude Sonnet 5.5)

| Task | Steps | Cost |
|---|---|---|
| "What time does Geisel Library close today?" (live web) | 3 | ~$0.025 |
| Hold a bus seat: search, confirm, ask name, book | 8 | ~$0.05 |
| Same task with a $0.02 cap | 2, then stopped | $0.016 (cap honored) |

Default cap: $0.15 per task, about 2× the most expensive normal run.

## Repo layout

| Path | Owner | What |
|---|---|---|
| `dialup/agent/` | Sirui | Agent loop, browser wrapper, supervisor, tests, local runner |
| `dialup/telephony/` | Kanwar | Twilio inbound calls, `ask_user`, `confirm_with_user`, `notify_result` |
| `dialup/web/` | Kanwar | Live dashboard for the demo |
| `dialup/db.py` | Kanwar | SQLite tasks + steps tables |
| `docs/CONTRACT.md` | both | The interface between the agent and the phone side |

## Run the agent without a phone

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# local demo site (fictional bus company, never blocks the browser)
python -m dialup.agent.run_local --fake-site --headed "hold me a seat on the cheapest bus to LA tomorrow"
# live web
python -m dialup.agent.run_local --headed "what time does Geisel Library at UCSD close today"
# trigger the budget stop on purpose
python -m dialup.agent.run_local --max-cost 0.02 --headed "compare prices for every Greyhound bus from San Diego to LA this week"
# Mandarin
python -m dialup.agent.run_local --lang zh --fake-site "帮我订明天去洛杉矶最便宜的巴士"

# tests
python -m pytest dialup/agent -q
```

Without a phone, the agent's questions and confirmations appear in the terminal.

## How we used AI coding tools

- **Contract first.** Before writing code we agreed on the task states, the two SQLite tables,
  and the function signatures between the agent and the phone side (`docs/CONTRACT.md`).
  That let two people, each working with an AI assistant, build in parallel without blocking.
- **Claude (claude.ai)** wrote the agent loop, supervisor, browser wrapper, fake demo site and
  tests from that contract, and ran them with mocks and a scripted fake model.
- **Every change was tested with real runs.** That caught two API problems before integration:
  a tool-choice setting the model rejects, and signed reasoning blocks that break when old
  pages are trimmed from history. It also caught the budget cap overshooting, which led to the
  predictive "stop before crossing" rule.
- Kanwar: _add how you used your tools for the phone side and dashboard._

## Team

Sirui Wang · Kanwar
