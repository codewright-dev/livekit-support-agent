"""Try the knowledge lookup offline, no keys needed:  python scripts/ask.py "my light is blinking amber" """

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from support_agent.desk import SupportDesk  # noqa: E402
from support_agent.retrieval import ManualIndex  # noqa: E402

MANUAL = Path(__file__).resolve().parent.parent / "manual" / "aeroflow-t2.md"
desk = SupportDesk(ManualIndex.from_file(MANUAL))
questions = sys.argv[1:] or [
    "my thermostat won't connect to the wifi",
    "the screen says E1",
    "can I return it, I bought it two weeks ago",
    "can it control my garage door",
]
for q in questions:
    print(f"\n\033[1mQ: {q}\033[0m\n{desk.search_manual(q)}")
