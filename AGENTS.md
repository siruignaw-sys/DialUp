# Notes for AI coding agents working in this repo

- Read `docs/CONTRACT.md` first. It is the interface between `dialup/agent/` (Sirui) and
  `dialup/telephony/`, `dialup/web/`, `dialup/db.py` (Kanwar). Don't change it without both agreeing.
- Entry point for the phone side: `from dialup.agent.agent import run_task`, then
  `asyncio.create_task(run_task(task_id))` after creating the task row.
- `run_task` with no `deps` imports `dialup.db` (get_task, update_task, add_step, get_steps; sync)
  and `dialup.telephony` (ask_user, confirm_with_user, notify_result; async).
  `dialup/telephony/__init__.py` must export those three.
- Timestamps are ISO 8601 UTC strings. `steps.new_info` is NULL when a step learned nothing.
- The agent must never type passwords, card numbers or government IDs, and must call
  `confirm_with_user` before any irreversible action. Keep it that way.
- Secrets live in `.env` (gitignored). Never commit keys.
- Tests: `python -m pytest dialup/agent -q`. Run them before pushing changes to `dialup/agent/`.
