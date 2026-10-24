# dialup/agent (Sirui)

Agent loop (Claude + Playwright) and supervisor. Contract: `docs/CONTRACT.md`.

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=...
```

## Run without a phone
```bash
# backup demo site (local, never blocks us)
python -m dialup.agent.run_local --fake-site --headed "hold me a seat on the cheapest bus to LA tomorrow"
# real web
python -m dialup.agent.run_local "what time does the UCSD library close today"
# Mandarin
python -m dialup.agent.run_local --lang zh --fake-site "帮我订明天去洛杉矶最便宜的巴士"
# force a supervisor stop for the demo
python -m dialup.agent.run_local --max-steps 4 "find every bus company in California"
```
`ask_user` / `confirm` prompt in the terminal instead of calling.

## Tests
```bash
python -m pytest dialup/agent -q
```

## Files
- `supervisor.py` — `check(task, steps)`: max_steps, timeout, over_budget, looping, stuck
- `agent.py` — `run_task(task_id)`; one tool per turn; writes a steps row per action
- `browser.py` — Playwright wrapper; elements are numbered so Claude clicks by number
- `dev_mocks.py` — in-memory db + terminal phone, so this runs without Kanwar's code
- `fake_site/` — fictional bus site (backup demo) and a login-wall trap page

## Plugging into Kanwar's side
`run_task(task_id)` with no `deps` imports `dialup.db` (get_task, update_task, add_step, get_steps)
and `dialup.telephony` (ask_user, confirm_with_user, notify_result). Make sure
`dialup/telephony/__init__.py` exports those three.
