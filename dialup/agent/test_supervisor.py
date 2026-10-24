"""Run with: python -m pytest dialup/agent/test_supervisor.py -q"""
from datetime import datetime, timedelta, timezone

from dialup.agent.supervisor import check

T0 = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


def task(**over):
    t = {"max_steps": 25, "max_seconds": 300, "max_cost_usd": 0.50,
         "cost_usd": 0, "created_at": T0.isoformat()}
    t.update(over)
    return t


def step(action, target, page, info=None, cost=0.01):
    return {"action": action, "target": target, "page_hash": page,
            "new_info": info, "cost_usd": cost}


NOW = T0 + timedelta(seconds=60)


def test_healthy_run_continues():
    steps = [
        step("navigate", "https://bus.example", "p1"),
        step("type", "#2 San Diego", "p1", "filled origin"),
        step("type", "#3 Los Angeles", "p1", "filled destination"),
        step("click", "#5 Search", "p2", "3 buses listed, cheapest $12 at 9am"),
        step("click", "#9 Hold seat", "p3", "hold form needs a name"),
    ]
    assert check(task(), steps, NOW) == ("continue", None)


def test_revisiting_search_page_once_is_not_a_loop():
    steps = [
        step("navigate", "https://bus.example", "p1"),
        step("click", "#5 Search", "p2", "results"),
        step("navigate", "https://bus.example", "p1"),
        step("click", "#5 Search", "p2", "results again, different date"),
    ]
    assert check(task(), steps, NOW) == ("continue", None)


def test_same_click_three_times_is_looping():
    steps = [step("navigate", "https://bus.example", "p1", "home")] + [
        step("click", "#7 Next", "p4") for _ in range(3)
    ]
    assert check(task(), steps, NOW) == ("stop", "looping")


def test_bouncing_between_two_pages_without_info_is_stuck():
    steps = []
    for i in range(6):
        steps.append(step("click", f"#{i} link", "pA" if i % 2 else "pB"))
    assert check(task(), steps, NOW) == ("stop", "stuck")


def test_exploring_new_pages_without_info_is_not_stuck_yet():
    steps = [step("click", f"#{i}", f"p{i}") for i in range(6)]
    assert check(task(), steps, NOW) == ("continue", None)


def test_long_run_with_no_info_is_stuck():
    steps = [step("click", f"#{i}", f"p{i}") for i in range(12)]
    assert check(task(), steps, NOW) == ("stop", "stuck")


def test_over_budget():
    steps = [step("navigate", "u", f"p{i}", "x", cost=0.2) for i in range(3)]
    assert check(task(), steps, NOW) == ("stop", "over_budget")


def test_max_steps():
    steps = [step("navigate", "u", f"p{i}", "x") for i in range(5)]
    assert check(task(max_steps=5), steps, NOW) == ("stop", "max_steps")


def test_timeout():
    late = T0 + timedelta(seconds=301)
    assert check(task(), [step("navigate", "u", "p", "x")], late) == ("stop", "timeout")


def test_ask_user_steps_do_not_count_as_loops():
    steps = [step("navigate", "u", "p1", "x")] + [
        step("ask_user", "What is your name?", "p1") for _ in range(3)
    ]
    assert check(task(), steps, NOW) == ("continue", None)
