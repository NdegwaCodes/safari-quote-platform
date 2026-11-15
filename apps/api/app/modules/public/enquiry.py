from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MAX_MESSAGE = 4000
MAX_NAME = 200
MAX_EMAIL = 255
MAX_PHONE = 50
MAX_DESTINATION = 200
MAX_PAX = 10_000

NO_NAME = "enquiry_no_name"
NO_REPLY_TO = "enquiry_no_contact"
BAD_EMAIL = "enquiry_bad_email"
BAD_WINDOW = "enquiry_bad_dates"
BAD_PAX = "enquiry_bad_pax"
TOO_LONG = "enquiry_too_long"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class EnquiryRefused(Exception):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Submitted:

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    destination: str | None = None
    travel_from: date | None = None
    travel_to: date | None = None
    pax: int | None = None
    message: str | None = None
    page: str | None = None
    trap: str | None = None


@dataclass(frozen=True)
class Accepted:

    name: str
    email: str | None
    phone: str | None
    destination: str | None
    travel_from: date | None
    travel_to: date | None
    pax: int | None
    message: str
    page: str | None
    discard: bool = False
    notes: tuple[str, ...] = ()


def _clean(value: str | None, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] if text else None


def check_enquiry(form: Submitted, *, today: date) -> Accepted:
    if (form.trap or "").strip():
        return Accepted(
            name="",
            email=None,
            phone=None,
            destination=None,
            travel_from=None,
            travel_to=None,
            pax=None,
            message="",
            page=_clean(form.page, 200),
            discard=True,
        )

    name = _clean(form.name, MAX_NAME)
    if not name:
        raise EnquiryRefused(
            NO_NAME, "Please tell us your name so we know who we are writing to."
        )

    email = _clean(form.email, MAX_EMAIL)
    phone = _clean(form.phone, MAX_PHONE)
    if not email and not phone:
        raise EnquiryRefused(
            NO_REPLY_TO,
            "Please leave an email address or a telephone number, otherwise we "
            "have no way to answer you.",
        )
    if email and not _EMAIL.match(email):
        raise EnquiryRefused(
            BAD_EMAIL,
            f"'{email}' does not look like an email address. Check it, or "
            f"leave a telephone number instead.",
        )

    message = (form.message or "").strip()
    if len(message) > MAX_MESSAGE:
        raise EnquiryRefused(
            TOO_LONG,
            f"Your message is longer than we can take ({len(message)} "
            f"characters against a limit of {MAX_MESSAGE}). Send us the outline "
            f"and we will call you.",
        )

    if form.pax is not None and (form.pax < 1 or form.pax > MAX_PAX):
        raise EnquiryRefused(
            BAD_PAX, "Please give the number of travellers as a whole number."
        )

    if form.travel_from and form.travel_to and form.travel_to < form.travel_from:
        raise EnquiryRefused(
            BAD_WINDOW,
            "The return date is before the departure date. Have they been "
            "entered the wrong way round?",
        )

    notes: list[str] = []
    if form.travel_from and form.travel_from < today:
        notes.append(
            f"Travel date given as {form.travel_from:%d %B %Y}, which has "
            f"already passed — check it when you reply."
        )
    if not message:
        notes.append("No message was left with the enquiry.")

    return Accepted(
        name=name,
        email=email,
        phone=phone,
        destination=_clean(form.destination, MAX_DESTINATION),
        travel_from=form.travel_from,
        travel_to=form.travel_to,
        pax=form.pax,
        message=message,
        page=_clean(form.page, 200),
        notes=tuple(notes),
    )


def as_log_entry(accepted: Accepted) -> str:
    lines: list[str] = []
    if accepted.message:
        lines.append(accepted.message)
    else:
        lines.append("(No message left.)")
    detail: list[str] = []
    if accepted.destination:
        detail.append(f"Interested in: {accepted.destination}")
    if accepted.travel_from:
        window = f"{accepted.travel_from:%d %b %Y}"
        if accepted.travel_to:
            window += f" to {accepted.travel_to:%d %b %Y}"
        detail.append(f"Travel: {window}")
    if accepted.pax:
        detail.append(f"Travellers: {accepted.pax}")
    if accepted.page:
        detail.append(f"Enquired from: {accepted.page}")
    if detail:
        lines.append("")
        lines.extend(detail)
    if accepted.notes:
        lines.append("")
        lines.extend(accepted.notes)
    return "\n".join(lines)


__all__ = [
    "BAD_EMAIL",
    "BAD_PAX",
    "BAD_WINDOW",
    "MAX_MESSAGE",
    "MAX_PAX",
    "NO_NAME",
    "NO_REPLY_TO",
    "TOO_LONG",
    "Accepted",
    "EnquiryRefused",
    "Submitted",
    "as_log_entry",
    "check_enquiry",
]
