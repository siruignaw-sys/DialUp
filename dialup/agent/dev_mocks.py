"""Stand-ins for Kanwar's db.py and telephony, so the agent runs from a terminal.

ask_user / confirm_with_user read from your keyboard instead of calling a phone.
"""
import asyncio
import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

_tasks = {}
_steps = {}
_ids = itertools.count(1)


def create_task(request, language="en", phone="+10000000000", **limits):
    task_id = next(_ids)
    now = datetime.now(timezone.utc).isoformat()
    _tasks[task_id] = {"id": task_id, "phone": phone, "language": language,
                       "request": request, "status": "received", "stop_reason": None,
                       "result": None, "max_steps": 25, "max_seconds": 300,
                       "max_cost_usd": 0.50, "cost_usd": 0.0,
                       "created_at": now, "updated_at": now, **limits}
    _steps[task_id] = []
    return task_id


def get_task(task_id):
    return dict(_tasks[task_id])


def update_task(task_id, **fields):
    _tasks[task_id].update(fields, updated_at=datetime.now(timezone.utc).isoformat())


def add_step(task_id, **fields):
    _steps[task_id].append({"task_id": task_id, **fields})
    s = fields
    info = f"  +info: {s.get('new_info')}" if s.get("new_info") else ""
    print(f"  step {s.get('n'):>2} {s.get('action'):<9} {str(s.get('target'))[:60]:<60} "
          f"${s.get('cost_usd', 0):.4f}{info}")


def get_steps(task_id):
    return [dict(s) for s in _steps[task_id]]


async def ask_user(task_id, question):
    print(f"\n📞 AGENT ASKS: {question}")
    answer = await asyncio.to_thread(input, "   your answer (blank = no answer): ")
    return answer.strip() or None


async def confirm_with_user(task_id, summary):
    print(f"\n📞 CONFIRM: {summary}")
    answer = await asyncio.to_thread(input, "   press 1 to confirm, 2 to cancel: ")
    return answer.strip() == "1"


async def notify_result(task_id):
    t = _tasks[task_id]
    print(f"\n📞 CALLBACK  status={t['status']}  reason={t['stop_reason']}  cost=${t['cost_usd']:.4f}")
    print(f"   \"{t['result']}\"")


deps = SimpleNamespace(get_task=get_task, update_task=update_task, add_step=add_step,
                       get_steps=get_steps, ask_user=ask_user,
                       confirm_with_user=confirm_with_user, notify_result=notify_result)
