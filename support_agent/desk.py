"""Support-desk logic used by the voice agent's tools. Pure Python, so it is unit-tested without LiveKit."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .retrieval import ManualIndex

WARRANTY_YEARS = 2
RETURN_DAYS = 30
# Calibrated on this manual: real questions score >= 2.3, off-topic ones ("garage door", "Alexa") score < 2.
# Re-check against a set of sample questions when the knowledge base changes.
MIN_SCORE = 2.2
SERIAL_RE = re.compile(r"^AF[- ]?T2[- ]?(\d{6})$", re.IGNORECASE)


class SupportDesk:
    def __init__(self, index: ManualIndex, ticket_dir: str | Path = "data/tickets", today: date | None = None):
        self.index = index
        self.ticket_dir = Path(ticket_dir)
        self._today = today

    @property
    def today(self) -> date:
        return self._today or datetime.now(timezone.utc).date()

    def search_manual(self, question: str) -> str:
        """Return the most relevant manual excerpts, or a clear 'not covered' signal for the LLM."""
        hits = [(s, score) for s, score in self.index.search(question, top_k=2) if score >= MIN_SCORE]
        if not hits:
            return "NOT_IN_MANUAL: the manual does not cover this. Do not guess; offer a ticket or a human agent."
        return "\n\n".join(f"[{s.title}]\n{s.text}" for s, _ in hits)

    def check_warranty(self, serial: str, purchase_date: str) -> dict:
        serial = serial.strip().upper()
        if not SERIAL_RE.match(serial):
            return {"ok": False, "message": "That serial number doesn't look right. It starts with AF-T2 followed by six digits."}
        try:
            bought = date.fromisoformat(purchase_date)
        except ValueError:
            return {"ok": False, "message": "Ask for the purchase date as day, month and year."}
        if bought > self.today:
            return {"ok": False, "message": "The purchase date is in the future. Confirm it with the caller."}
        expires = bought.replace(year=bought.year + WARRANTY_YEARS) if not (bought.month == 2 and bought.day == 29) else date(bought.year + WARRANTY_YEARS, 3, 1)
        return {
            "ok": True,
            "in_warranty": self.today <= expires,
            "warranty_expires": expires.isoformat(),
            "refund_eligible": self.today <= bought + timedelta(days=RETURN_DAYS),
        }

    def create_ticket(self, name: str, phone: str, issue: str, priority: str = "normal") -> dict:
        if not name.strip() or len(re.sub(r"\D", "", phone)) < 7 or not issue.strip():
            return {"ok": False, "message": "A ticket needs the caller's name, a callback number and a short description."}
        priority = priority if priority in {"low", "normal", "urgent"} else "normal"
        ticket = {
            "id": f"T-{uuid.uuid4().hex[:6].upper()}",
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": name.strip(),
            "phone": phone.strip(),
            "issue": issue.strip()[:1000],
            "priority": priority,
        }
        self.ticket_dir.mkdir(parents=True, exist_ok=True)
        (self.ticket_dir / f"{ticket['id']}.json").write_text(json.dumps(ticket, indent=2))
        return {"ok": True, "ticket_id": ticket["id"], "spoken_id": " ".join(ticket["id"].replace("T-", ""))}


def within_support_hours(now: datetime) -> bool:
    """Human agents: Mon-Fri 8 AM-8 PM US Eastern (fixed UTC-5 is close enough for routing; use zoneinfo in production)."""
    et = now.astimezone(timezone(timedelta(hours=-5)))
    return et.weekday() < 5 and 8 <= et.hour < 20
