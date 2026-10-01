"""
WasseLead — WhatsApp lead follow-up for small Indian businesses.

The problem this solves is narrow and real. A clinic, gym or shop gets 20–60
leads a week on WhatsApp. Most of them go cold because nobody follows up. The
owner cannot follow up personally because they are busy doing the actual work.

This tool takes that list, decides who needs what follow-up, writes the message
in the owner's own tone, and produces a copy-paste-ready plan. It does NOT
auto-send. Sending is manual and stays manual, because:

  - bulk WhatsApp automation violates WhatsApp's terms and gets the business
    number banned, which would cost the client far more than the tool costs;
  - the owner is the one who can tell whether "no reply" means "not interested"
    or "busy this week".

Being deliberately not-automatic is a feature, not a limitation. A tool that
bans its user's number is not a tool.

Zero dependencies. Standard library only.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    BOOKED = "booked"
    LOST = "lost"


# Phrases that mean "stop messaging me". This is deliberately fail-safe: if a
# lead's own words could plausibly read as an opt-out, we skip them. A wrongly
# skipped lead costs one lost follow-up; a message sent to someone who asked to
# be left alone costs the client's number and their trust.
_OPT_OUT_PATTERNS = (
    r"\bstop\b", r"\bunsubscribe\b", r"\bopt[\s\-_]?out\b",
    r"\bremove me\b", r"\bremove my\b", r"\bdo not (?:contact|call|message)\b",
    r"\bdon'?t (?:contact|call|message)\b", r"\bleave me alone\b",
    r"\bno longer (?:wish|want)\b", r"\bdelete my\b", r"\bnot interested\b",
    r"\bblock me\b", r"\bcomplain\b",
)

_OPT_OUT_RE = re.compile("|".join(_OPT_OUT_PATTERNS), re.IGNORECASE)


def looks_opted_out(message: str) -> bool:
    """True when the message text itself reads as an opt-out request."""
    return bool(_OPT_OUT_RE.search(message or ""))


class LeadUrgency(str, Enum):
    """How badly this lead needs a reply, and why."""

    HOT = "hot"        # asked a question, got no answer
    WARM = "warm"      # said they are interested
    COLD = "cold"      # initial message only
    DO_NOT_DISTURB = "do_not_disturb"  # explicitly opted out or unsubscribed


# Reply-window targets. These are the numbers that actually get a reply back;
# they come from ordinary follow-up practice, not from anything clever.
URGENCY_WINDOW: dict[LeadUrgency, timedelta] = {
    LeadUrgency.HOT: timedelta(hours=2),
    LeadUrgency.WARM: timedelta(days=1),
    LeadUrgency.COLD: timedelta(days=2),
    LeadUrgency.DO_NOT_DISTURB: timedelta(days=3650),
}


@dataclass
class Lead:
    name: str
    phone: str
    message: str
    received_at: str  # ISO 8601
    replied: bool = False
    opted_out: bool = False
    booked: bool = False
    note: str = ""
    messages_sent: int = 0

    def age(self, now: datetime) -> timedelta:
        try:
            received = datetime.fromisoformat(self.received_at)
        except ValueError as e:
            raise ValueError(f"lead {self.name!r} has an invalid received_at: {e}") from e
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        return now - received

    def urgency(self) -> LeadUrgency:
        """Decide urgency from what the lead actually said.

        Order matters: an opt-out beats everything, and a booked lead is not
        urgent regardless of how long ago they wrote.
        """
        if self.opted_out or looks_opted_out(self.message):
            return LeadUrgency.DO_NOT_DISTURB
        if self.booked:
            return LeadUrgency.COLD
        if self.replied:
            # They wrote back and we have not answered. Most neglected lead.
            return LeadUrgency.HOT

        text = self.message.lower()
        # A question is the strongest buying signal there is.
        if "?" in self.message or any(
            w in text for w in ("price", "cost", "charges", "rate", "how much", "available", "timing")
        ):
            return LeadUrgency.HOT
        if any(w in text for w in ("interested", "interested in", "sure", "ok", "yes", "tell me more", "details")):
            return LeadUrgency.WARM
        return LeadUrgency.COLD


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------

def normalise_phone(raw: str, default_country: str = "91") -> str:
    """Turn any reasonable input into digits-only with a country code.

    Indian numbers arrive as +919876543210, 09876543210, 9876543210, or with
    spaces and dashes. All of those are the same person, so all of them must
    produce the same key, or the same lead gets messaged twice.
    """
    if raw is None:
        raise ValueError("phone is required")
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        raise ValueError(f"no digits found in phone {raw!r}")

    # 0091... / 91... / 0... prefixes all collapse to the 10-digit local number.
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]

    if len(digits) == 10:
        return f"{default_country}{digits}"
    if 11 <= len(digits) <= 15:
        return digits
    raise ValueError(f"phone {raw!r} does not look like a real number")


# ---------------------------------------------------------------------------
# Message generation
# ---------------------------------------------------------------------------

def _first_name(full: str) -> str:
    parts = full.strip().split()
    return parts[0] if parts else "there"


def compose_message(lead: Lead, business: dict, now: datetime) -> str:
    """Write the follow-up in the owner's own words.

    Templates use the owner's name and business so the message reads as though
    a person wrote it, because it will be sent by a person, from a personal
    WhatsApp number. That is the difference between a reply and an ignore.
    """
    name = _first_name(lead.name)
    owner = business.get("owner_name", "there")
    biz = business.get("name", "us")
    slots = {**business.get("slots", {})}

    if lead.booked:
        return (
            f"Hi {name}, this is {owner} from {biz}. Just confirming your appointment — "
            f"reply YES to confirm or RESCHEDULE if you need a different time."
        )

    if lead.replied:
        return (
            f"Hi {name}, sorry for the delay in replying — thank you for your message. "
            f"This is {owner} from {biz}. How can I help?"
        )

    # Ask about price? Answer it directly instead of making them ask twice.
    # Slot text is the owner's own writing, so it may or may not already end in
    # punctuation. Normalise to exactly one full stop: neither a run-on
    # ("month Shall I share") nor a double ("month.. Shall I share").
    def clean(value: str) -> str:
        v = value.strip().rstrip(".")
        return v + "." if v else v

    asked_price = any(w in lead.message.lower() for w in ("price", "cost", "charges", "rate", "how much"))
    if asked_price and slots.get("price"):
        return (
            f"Hi {name}, this is {owner} from {biz}. Thanks for asking — "
            f"{clean(slots['price'])} Want me to book you in?"
        )

    if slots.get("offer"):
        return (
            f"Hi {name}, this is {owner} from {biz}. Saw your message. "
            f"{clean(slots['offer'])} Shall I share timings?"
        )

    return (
        f"Hi {name}, this is {owner} from {biz}. Thanks for reaching out — "
        f"how can I help?"
    )


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

@dataclass
class QueueItem:
    lead: Lead
    urgency: LeadUrgency
    due_at: datetime
    message: str
    reason: str

    def overdue(self, now: datetime) -> bool:
        return now >= self.due_at


@dataclass
class Report:
    generated_at: str
    business: str
    total: int
    counts: dict[str, int] = field(default_factory=dict)
    items: list[QueueItem] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (name, reason)

    def to_json(self) -> str:
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "business": self.business,
                "total": self.total,
                "counts": self.counts,
                "skipped": [{"name": n, "reason": r} for n, r in self.skipped],
                "queue": [
                    {
                        "name": i.lead.name,
                        "phone": normalise_phone(i.lead.phone),
                        "urgency": i.urgency.value,
                        "due_at": i.due_at.isoformat(),
                        "overdue": i.overdue(datetime.fromisoformat(self.generated_at)),
                        "message": i.message,
                        "reason": i.reason,
                    }
                    for i in self.items
                ],
            },
            indent=2,
            ensure_ascii=False,
        )


def build_queue(leads: Iterable[Lead], business: dict, now: datetime) -> Report:
    """Turn a raw lead list into an ordered follow-up queue.

    Contacts already done with are removed rather than shown and ignored —
    a queue containing opt-outs is a queue people stop trusting.
    """
    report = Report(
        generated_at=now.isoformat(),
        business=business.get("name", "unknown"),
        total=0,
    )

    seen_phones: dict[str, str] = {}
    rows = list(leads)
    report.total = len(rows)

    for lead in rows:
        if lead.opted_out:
            report.skipped.append((lead.name, "opted out"))
            continue
        if lead.booked:
            # Booked leads still get one confirmation, but never sit in the
            # hot queue nagging about an appointment they already have.
            pass

        try:
            phone = normalise_phone(lead.phone)
        except ValueError as e:
            report.skipped.append((lead.name, str(e)))
            continue

        # The same person can appear twice if the sheet was merged badly. One
        # message per person, never two.
        if phone in seen_phones:
            report.skipped.append((lead.name, f"duplicate of {seen_phones[phone]}"))
            continue
        seen_phones[phone] = lead.name

        urgency = lead.urgency()
        if urgency is LeadUrgency.DO_NOT_DISTURB:
            report.skipped.append((lead.name, "do not disturb"))
            continue

        try:
            received = datetime.fromisoformat(lead.received_at)
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
        except ValueError:
            report.skipped.append((lead.name, "unparseable timestamp"))
            continue
        due_at = received + URGENCY_WINDOW[urgency]

        report.items.append(
            QueueItem(
                lead=lead,
                urgency=urgency,
                due_at=due_at,
                message=compose_message(lead, business, now),
                reason=_reason_for(lead, urgency),
            )
        )

    # Hottest first, then by how long overdue. This is the order to work in.
    order = {LeadUrgency.HOT: 0, LeadUrgency.WARM: 1, LeadUrgency.COLD: 2}
    report.items.sort(key=lambda i: (order[i.urgency], i.due_at))

    for item in report.items:
        report.counts[item.urgency.value] = report.counts.get(item.urgency.value, 0) + 1
    return report


def _reason_for(lead: Lead, urgency: LeadUrgency) -> str:
    if lead.booked:
        return "booked — send a confirmation, not a sales message"
    if lead.replied:
        return "they replied and have had no answer"
    if urgency is LeadUrgency.HOT:
        return "asked a question and got no answer"
    if urgency is LeadUrgency.WARM:
        return "showed interest but no reply"
    return "initial message, no reply yet"


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def load_leads(path: Path) -> list[Lead]:
    """Read leads from CSV or JSON. Missing optional columns get defaults."""
    text = path.read_text(encoding="utf-8")
    leads: list[Lead] = []

    if path.suffix.lower() == ".json":
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("leads", [])
    else:
        rows = list(csv.DictReader(text.splitlines()))

    for i, row in enumerate(rows, start=1):
        if isinstance(row, str):
            row = {"message": row}
        try:
            leads.append(
                Lead(
                    name=str(row.get("name", f"lead {i}")),
                    phone=str(row.get("phone", "")),
                    message=str(row.get("message", "")),
                    received_at=str(row.get("received_at", datetime.now(timezone.utc).isoformat())),
                    replied=str(row.get("replied", "")).lower() in ("1", "true", "yes", "y"),
                    opted_out=str(row.get("opted_out", "")).lower() in ("1", "true", "yes", "y"),
                    booked=str(row.get("booked", "")).lower() in ("1", "true", "yes", "y"),
                    note=str(row.get("note", "")),
                    messages_sent=int(row.get("messages_sent", 0) or 0),
                )
            )
        except (TypeError, ValueError) as e:
            raise ValueError(f"row {i} is invalid: {e}") from e

    return leads


def load_business(path: Path | None) -> dict:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_text(report: Report, now: datetime) -> None:
    print(f"\nLead follow-up — {report.business}")
    print("=" * 60)
    if report.skipped:
        print(f"Skipped {len(report.skipped)}:")
        for name, reason in report.skipped:
            print(f"  - {name}: {reason}")
    if not report.items:
        print("\nNothing to follow up. Every lead is handled.")
        return

    for item in report.items:
        late = "LATE " if item.overdue(now) else "     "
        print(f"\n[{item.urgency.value.upper():>4}] {item.lead.name}  {late}(due {item.due_at.isoformat()[:16]})")
        print(f"        {normalise_phone(item.lead.phone)}  — {item.reason}")
        print(f"        \"{item.message}\"")

    print("\n" + "=" * 60)
    print("Counts: " + ", ".join(f"{k}={v}" for k, v in sorted(report.counts.items())))
    print("Copy each message into WhatsApp yourself. Nothing is sent automatically.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("\nusage: wasselead.py LEADS.csv [--business config.json] [--json] [--now ISO]")
        return 0

    leads_path = Path(argv[0])
    if not leads_path.exists():
        print(f"error: no such file: {leads_path}", file=sys.stderr)
        return 1

    business: dict = {}
    as_json = False
    now = datetime.now(timezone.utc)

    i = 1
    while i < len(argv):
        if argv[i] == "--business":
            i += 1
            business = load_business(Path(argv[i])) if i < len(argv) else {}
        elif argv[i] == "--json":
            as_json = True
        elif argv[i] == "--now":
            i += 1
            if i < len(argv):
                try:
                    now = datetime.fromisoformat(argv[i])
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)
                except ValueError:
                    print(f"error: bad --now timestamp: {argv[i]}", file=sys.stderr)
                    return 1
        i += 1

    try:
        leads = load_leads(leads_path)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: could not read leads: {e}", file=sys.stderr)
        return 1

    report = build_queue(leads, business, now)
    print(report.to_json() if as_json else "", end="" if as_json else "")
    if as_json:
        print()
    else:
        _print_text(report, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
