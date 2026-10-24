"""Run the agent from a terminal, no phone needed.

  export ANTHROPIC_API_KEY=...
  python -m dialup.agent.run_local "find the cheapest bus from San Diego to LA tomorrow"
  python -m dialup.agent.run_local --fake-site "hold me a seat on the cheapest bus to LA" --headed
  python -m dialup.agent.run_local --lang zh "..."
"""
import argparse
import asyncio
from pathlib import Path

from dialup.agent import agent, dev_mocks

FAKE_SITE = Path(__file__).parent / "fake_site" / "bus.html"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("request")
    p.add_argument("--lang", default="en", choices=sorted(agent.LANGUAGES))
    p.add_argument("--headed", action="store_true", help="show the browser window")
    p.add_argument("--fake-site", action="store_true", help="start on the local backup bus site")
    p.add_argument("--max-steps", type=int, default=25)
    p.add_argument("--max-cost", type=float, default=0.50)
    p.add_argument("--max-seconds", type=int, default=300)
    a = p.parse_args()

    if a.fake_site:
        agent.START_URL = FAKE_SITE.resolve().as_uri()

    task_id = dev_mocks.create_task(a.request, language=a.lang, max_steps=a.max_steps,
                                    max_cost_usd=a.max_cost, max_seconds=a.max_seconds)
    print(f"Task {task_id}: {a.request}\n")
    asyncio.run(agent.run_task(task_id, deps=dev_mocks.deps, headless=not a.headed))


if __name__ == "__main__":
    main()
