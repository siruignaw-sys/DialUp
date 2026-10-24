"""Supervisor: decides after every step whether the agent may keep going.

check(task, steps) -> ("continue", None) | ("stop", reason)
reason is one of: max_steps, timeout, over_budget, looping, stuck

Every rule is based on numbers in the steps table, not on asking the LLM,
because the model doing the work is the one that loses track.
"""
from collections import Counter
from datetime import datetime, timezone

BROWSER_ACTIONS = {"navigate", "read", "click", "type"}

# Looping: the same (action, target, page) shows up this many times
# within the last LOOP_WINDOW browser steps.
LOOP_WINDOW = 8
LOOP_REPEATS = 3

# Stuck: the last STUCK_WINDOW browser steps produced no new info AND the
# agent kept landing on at most STUCK_MAX_PAGES distinct pages.
STUCK_WINDOW = 6
STUCK_MAX_PAGES = 2

# Hard stuck: no new info at all for this many browser steps, whatever the pages.
NO_INFO_LIMIT = 12


def _parse_time(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _has_info(step):
    info = step.get("new_info")
    return bool(info and str(info).strip())


def check(task, steps, now=None):
    now = _parse_time(now) or datetime.now(timezone.utc)

    # 1. Hard caps
    max_steps = task.get("max_steps") or 25
    if len(steps) >= max_steps:
        return "stop", "max_steps"

    started = _parse_time(task.get("created_at"))
    max_seconds = task.get("max_seconds") or 300
    if started and (now - started).total_seconds() > max_seconds:
        return "stop", "timeout"

    spent = sum(float(s.get("cost_usd") or 0) for s in steps)
    spent = max(spent, float(task.get("cost_usd") or 0))
    if spent >= float(task.get("max_cost_usd") or 0.50):
        return "stop", "over_budget"

    browser = [s for s in steps if s.get("action") in BROWSER_ACTIONS]

    # 2. Looping: repeating the same move on the same page
    recent = browser[-LOOP_WINDOW:]
    signatures = Counter(
        (s.get("action"), s.get("target"), s.get("page_hash")) for s in recent
    )
    if signatures and max(signatures.values()) >= LOOP_REPEATS:
        return "stop", "looping"

    # 3. Stuck: spinning on the same couple of pages without learning anything
    window = browser[-STUCK_WINDOW:]
    if len(window) == STUCK_WINDOW and not any(_has_info(s) for s in window):
        pages = {s.get("page_hash") for s in window}
        if len(pages) <= STUCK_MAX_PAGES:
            return "stop", "stuck"

    if len(browser) >= NO_INFO_LIMIT and not any(
        _has_info(s) for s in browser[-NO_INFO_LIMIT:]
    ):
        return "stop", "stuck"

    return "continue", None
