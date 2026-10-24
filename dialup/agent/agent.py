"""Agent loop: Claude drives a headless browser, one action per turn.

Contract (see docs/CONTRACT.md):
  async run_task(task_id, deps=None, headless=True)

deps provides: get_task, update_task, add_step, get_steps (sync, Kanwar's db.py)
               ask_user, confirm_with_user, notify_result (async, Kanwar's telephony)
If deps is None, the real modules are imported. dev_mocks.py has terminal fakes.
"""
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from anthropic import AsyncAnthropic

try:  # pick up ANTHROPIC_API_KEY etc. from a .env file at the repo root, if present
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from dialup.agent.browser import Browser, format_observation
from dialup.agent.supervisor import check

MODEL = os.getenv("DIALUP_MODEL", "claude-sonnet-5-5")
# USD per million tokens (Sonnet 5.5 list price). Update if you switch models.
PRICE_IN = float(os.getenv("DIALUP_PRICE_IN", "2.0"))
PRICE_OUT = float(os.getenv("DIALUP_PRICE_OUT", "10.0"))

LANGUAGES = {
    "en": "English",
    "zh": "Mandarin Chinese (simplified characters)",
    "hi": "Hindi",
    "es": "Spanish",
}

START_URL = "https://html.duckduckgo.com/html/"

FALLBACK_MESSAGES = {
    "en": "Sorry, something went wrong on my end and I couldn't finish your request.",
    "zh": "抱歉，我这边出了问题，没能完成您的请求。",
    "hi": "माफ़ कीजिए, मेरी तरफ़ कुछ गड़बड़ हो गई और मैं आपका काम पूरा नहीं कर पाया।",
    "es": "Lo siento, algo salió mal y no pude terminar su solicitud.",
}

_PROGRESS = {
    "type": "string",
    "description": ("Concrete new information or progress you got from the page you are "
                    "looking at right now (e.g. 'found 3 buses, cheapest $12'). "
                    "Empty string if nothing new."),
}

TOOLS = [
    {"name": "navigate", "description": "Open a URL in the browser.",
     "input_schema": {"type": "object", "properties": {
         "url": {"type": "string"}, "progress": _PROGRESS},
         "required": ["url", "progress"]}},
    {"name": "click", "description": "Click an element by its number from ELEMENTS.",
     "input_schema": {"type": "object", "properties": {
         "element_id": {"type": "integer"}, "progress": _PROGRESS},
         "required": ["element_id", "progress"]}},
    {"name": "type_text", "description": "Type into an input by its number. Set submit=true to press Enter after.",
     "input_schema": {"type": "object", "properties": {
         "element_id": {"type": "integer"}, "text": {"type": "string"},
         "submit": {"type": "boolean"}, "progress": _PROGRESS},
         "required": ["element_id", "text", "progress"]}},
    {"name": "select_option", "description": "Pick an option in a dropdown (select) by its visible text.",
     "input_schema": {"type": "object", "properties": {
         "element_id": {"type": "integer"}, "option": {"type": "string"}, "progress": _PROGRESS},
         "required": ["element_id", "option", "progress"]}},
    {"name": "ask_user", "description": ("Phone the caller to ask for information only they know "
                                         "(name, preference). One short question, max 20 words."),
     "input_schema": {"type": "object", "properties": {
         "question": {"type": "string"}}, "required": ["question"]}},
    {"name": "confirm", "description": ("Phone the caller to approve an irreversible action "
                                        "(booking, submitting, buying). REQUIRED before any such action."),
     "input_schema": {"type": "object", "properties": {
         "summary": {"type": "string", "description": "What you are about to do, one spoken sentence."}},
         "required": ["summary"]}},
    {"name": "finish", "description": "The task is done. Report the result to the caller.",
     "input_schema": {"type": "object", "properties": {
         "result": {"type": "string"}}, "required": ["result"]}},
    {"name": "give_up", "description": ("Stop because the task is impossible or blocked "
                                        "(login wall, CAPTCHA, paywall, site down)."),
     "input_schema": {"type": "object", "properties": {
         "reason": {"type": "string"}}, "required": ["reason"]}},
]

ACTION_NAMES = {"navigate": "navigate", "click": "click", "type_text": "type",
                "select_option": "type", "ask_user": "ask_user", "confirm": "confirm",
                "finish": "finish", "give_up": "give_up"}


def system_prompt(language):
    lang = LANGUAGES.get(language, "English")
    return f"""You are Dial-Up, a web agent working for someone who called a phone number.
They cannot see a screen. You act in a real web browser, one tool call per turn.

How to work:
- Always respond with exactly one tool call, never plain text.
- Refer to page elements by their number in ELEMENTS. Numbers change after every action.
- If you don't know which site to use, search with DuckDuckGo (you start there).
- Fill the `progress` field honestly; leave it empty when the last action got you nothing new.
- Need something only the caller knows (name, preference)? Use ask_user.
- Before ANY irreversible action (booking, holding, submitting a form, paying) use confirm first.
- Never enter passwords, card numbers, or government ID numbers. If a site needs a login, CAPTCHA, or payment, use give_up and say why.
- Don't repeat an action that already failed. Try something different or give_up.

Everything you say to the caller (ask_user, confirm, finish, give_up) will be read aloud over the phone:
write it in {lang}, at most 2 short sentences, no URLs, no markdown, no lists."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _cost(usage):
    return (usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1_000_000


def real_deps():
    from dialup import db
    from dialup.telephony import ask_user, confirm_with_user, notify_result
    return SimpleNamespace(get_task=db.get_task, update_task=db.update_task,
                           add_step=db.add_step, get_steps=db.get_steps,
                           ask_user=ask_user, confirm_with_user=confirm_with_user,
                           notify_result=notify_result)


def _shrink_old_pages(messages):
    """Keep only the newest page observation in full, to hold token cost down."""
    seen_latest = False
    for msg in reversed(messages):
        if msg["role"] != "user" or not isinstance(msg["content"], list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict):
                continue
            key = "content" if block.get("type") == "tool_result" else "text"
            body = block.get(key)
            if not isinstance(body, str) or "\nELEMENTS (use the number" not in body:
                continue
            if not seen_latest:
                seen_latest = True
                continue
            head, _, page = body.partition("URL: ")
            block[key] = f"{head}(older page omitted) URL: {page.split(chr(10), 1)[0]}"


async def _execute(name, args, browser, deps, task_id):
    """Run one tool. Returns (text for the model, observation or None, terminal or None)."""
    if name == "navigate":
        obs = await browser.navigate(args["url"])
        return format_observation(obs), obs, None
    if name == "click":
        obs = await browser.click(args["element_id"])
        return format_observation(obs), obs, None
    if name == "type_text":
        obs = await browser.type(args["element_id"], args["text"], bool(args.get("submit")))
        return format_observation(obs), obs, None
    if name == "select_option":
        obs = await browser.select(args["element_id"], args["option"])
        return format_observation(obs), obs, None
    if name == "ask_user":
        t0 = time.monotonic()
        answer = await deps.ask_user(task_id, args["question"])
        _extend_deadline(deps, task_id, time.monotonic() - t0)
        text = f"Caller answered: {answer}" if answer else "Caller did not answer."
        return text + "\n\n" + format_observation(await browser.observe()), None, None
    if name == "confirm":
        t0 = time.monotonic()
        ok = await deps.confirm_with_user(task_id, args["summary"])
        _extend_deadline(deps, task_id, time.monotonic() - t0)
        text = ("Caller CONFIRMED. Go ahead." if ok else
                "Caller DECLINED. Do not do it. Use finish to tell them it was cancelled.")
        return text + "\n\n" + format_observation(await browser.observe()), None, None
    if name == "finish":
        return "", None, ("done", None, args["result"])
    if name == "give_up":
        return "", None, ("gave_up", None, args["reason"])
    return f"Unknown tool {name}.", None, None


def _extend_deadline(deps, task_id, waited_seconds):
    """Time spent on the phone with the caller shouldn't count against the agent's clock."""
    task = deps.get_task(task_id)
    deps.update_task(task_id, max_seconds=int((task.get("max_seconds") or 300) + waited_seconds))


def _target(name, args):
    if name == "navigate":
        return args.get("url")
    if name == "click":
        return f"#{args.get('element_id')}"
    if name == "type_text":
        return f"#{args.get('element_id')} {args.get('text')}"
    if name == "select_option":
        return f"#{args.get('element_id')} = {args.get('option')}"
    return args.get("question") or args.get("summary") or args.get("result") or args.get("reason")


async def _summarize_stop(client, system, messages, reason, language):
    """Supervisor stopped us: ask Claude for a 2-sentence spoken summary of partial findings."""
    prompt = (f"SUPERVISOR: the task was stopped (reason: {reason}). Do not call tools. "
              f"In {LANGUAGES.get(language, 'English')}, in at most 2 short spoken sentences, "
              "tell the caller what you found so far and why you stopped.")
    messages[-1]["content"].append({"type": "text", "text": prompt})
    resp = await client.messages.create(model=MODEL, max_tokens=300, system=system,
                                        tools=TOOLS, tool_choice={"type": "none"},
                                        messages=messages)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return text, _cost(resp.usage)


async def run_task(task_id, deps=None, headless=True, client=None):
    deps = deps or real_deps()
    client = client or AsyncAnthropic()
    task = deps.get_task(task_id)
    language = task.get("language") or "en"
    system = system_prompt(language)
    deps.update_task(task_id, status="running")

    cost = float(task.get("cost_usd") or 0)
    n = len(deps.get_steps(task_id))
    final = None
    browser = Browser(headless=headless)
    try:
        await browser.start()
        obs = await browser.navigate(START_URL)
        messages = [{"role": "user", "content": [{"type": "text", "text":
                     f"CALLER'S REQUEST: {task['request']}\n\nCurrent page:\n{format_observation(obs)}"}]}]

        nudges = 0
        while True:
            resp = await client.messages.create(
                model=MODEL, max_tokens=1024, system=system, tools=TOOLS,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=messages)
            step_cost = _cost(resp.usage)
            cost += step_cost
            tool = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
            messages.append({"role": "assistant", "content": resp.content})
            if tool is None:
                # Model answered in plain text instead of calling a tool: nudge it, at most twice.
                nudges += 1
                if nudges > 2:
                    raise RuntimeError("model kept replying without calling a tool")
                messages.append({"role": "user", "content": [{"type": "text", "text":
                                 "You must respond by calling exactly one tool."}]})
                continue
            nudges = 0

            name, args = tool.name, dict(tool.input or {})
            result_text, obs, terminal = await _execute(name, args, browser, deps, task_id)

            n += 1
            deps.add_step(task_id, n=n, action=ACTION_NAMES.get(name, name),
                          target=_target(name, args),
                          url=obs["url"] if obs else browser.page.url,
                          page_hash=obs["page_hash"] if obs else None,
                          new_info=(args.get("progress") or "").strip() or None,
                          cost_usd=step_cost, created_at=_now())
            deps.update_task(task_id, cost_usd=cost)

            if terminal:
                final = terminal
                break

            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool.id, "content": result_text}]})
            _shrink_old_pages(messages)

            decision, reason = check(deps.get_task(task_id), deps.get_steps(task_id))
            if decision == "stop":
                try:
                    summary, extra = await _summarize_stop(client, system, messages, reason, language)
                    cost += extra
                except Exception:
                    summary = ""
                final = ("stopped", reason, summary or FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["en"]))
                break
    except Exception as e:
        print(f"[agent] task {task_id} crashed: {e!r}")
        final = ("gave_up", "error", FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["en"]))
    finally:
        try:
            await browser.close()
        except Exception:
            pass

    status, reason, result = final
    deps.update_task(task_id, status=status, stop_reason=reason, result=result, cost_usd=cost)
    await deps.notify_result(task_id)
