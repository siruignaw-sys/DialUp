# Dial-Up: interface contract (Sirui ↔ Kanwar)

## Ownership
- Kanwar: FastAPI server, Twilio telephony, db.py, live dashboard
  Folders: dialup/telephony/, dialup/web/, dialup/db.py
- Sirui: agent loop (Claude + Playwright) and supervisor
  Folders: dialup/agent/
- Don't edit the other person's folder without asking. Changes to db.py need both to agree.

## Task lifecycle
received → running ⇄ waiting_on_user → done | gave_up | stopped
Every end state triggers exactly one callback via notify_result().

## SQLite schema (db.py, Kanwar)
tasks:
  id INTEGER PK, phone TEXT, language TEXT ('en' | 'zh' | 'hi' | 'es'),
  request TEXT, status TEXT, stop_reason TEXT NULL,
  result TEXT NULL,          -- spoken-ready, in task.language, max 2 sentences, ALWAYS set at end
  max_steps INT DEFAULT 25, max_seconds INT DEFAULT 300, max_cost_usd REAL DEFAULT 0.50,
  cost_usd REAL DEFAULT 0, created_at TEXT (ISO 8601 UTC), updated_at TEXT

steps:
  id INTEGER PK, task_id INT, n INT,
  action TEXT ('navigate' | 'read' | 'click' | 'type' | 'ask_user' | 'confirm' | 'finish' | 'give_up'),
  target TEXT,               -- url, element, typed text, or question
  url TEXT,                  -- page URL after the action
  page_hash TEXT,            -- hash of visible page text after the action
  new_info TEXT NULL,        -- new facts learned this step, NULL if none
  cost_usd REAL, created_at TEXT

db.py helpers (sync, return dicts): get_task(id), update_task(id, **fields),
add_step(task_id, **fields), get_steps(task_id)

## Kanwar provides (dialup/telephony/__init__.py exports these), all async
- On inbound call: create task row (status='received'), then start
  asyncio.create_task(run_task(task_id)) and hang up.
- async ask_user(task_id, question: str) -> str | None
- async confirm_with_user(task_id, summary: str) -> bool   ("Press 1 to confirm, 2 to cancel")
- async notify_result(task_id) -> None   (calls with task.result; for 'stopped', prefix a line based on stop_reason)

## Sirui provides (dialup/agent/)
- async run_task(task_id) -> None   (from dialup.agent.agent import run_task)
- check(task, steps) -> (decision, reason)   (from dialup.agent.supervisor import check)
  decision: 'continue' | 'stop'; reason: None | 'max_steps' | 'timeout' | 'over_budget' | 'looping' | 'stuck'
- Note: run_task extends task.max_seconds by time spent on the phone with the caller.
