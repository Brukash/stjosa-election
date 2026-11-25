"""Contact validation shared by register import, voter creation and correction.

Every notice this system sends depends on a usable address, and a malformed one
fails permanently at the mail server however often it is retried. An address is
therefore checked when it enters the register and whenever it is corrected,
instead of being accepted and discovered when a member complains that nothing
arrived.

The check is deliberately structural rather than a full RFC 5322 parser: the
addresses on an alumni register are ordinary mailbox addresses, and the goal is
to reject the typos and stray characters that no mail server will ever accept.
"""
from __future__ import annotations

import re

# Local part: ordinary atoms plus the punctuation a real mailbox may use. Quotes,
# apostrophes, commas, spaces, parentheses and angle brackets are excluded, which
# is what makes a value such as `name@gmail.com'74` fail here rather than later.
_LOCAL = r"[A-Za-z0-9!#$%&*+/=?^_`{|}~.-]+"
# One domain label: no leading or trailing hyphen.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
EMAIL_RE = re.compile(rf"^{_LOCAL}@{_LABEL}(?:\.{_LABEL})*\.[A-Za-z]{{2,}}$")

# Characters that can never be part of an address and are named in the message,
# so the committee can see exactly what to remove.
IMPOSSIBLE_CHARACTERS = "'\"(),;:<>[]\\"


def clean_email(value: str | None) -> str | None:
    """The address as stored, or None when nothing usable was supplied."""
    if value is None:
        return None
    return value.strip() or None


def email_problem(value: str | None) -> str | None:
    """Why an address cannot receive a notice, or None when it can be used.

    The reason is shown to the committee member doing the import or correction,
    so it names what is wrong instead of saying "invalid email".
    """
    email = clean_email(value)
    if email is None:
        return "No email address is recorded."
    if len(email) > 254:
        return "The address is longer than 254 characters."
    if email.count("@") != 1:
        return "The address must contain exactly one @."
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "The address needs a name before the @ and a domain after it."
    if len(local) > 64:
        return "The part before the @ is longer than 64 characters."
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return "The part before the @ has a misplaced dot."
    if ".." in domain:
        return "The domain has two dots in a row."
    if not EMAIL_RE.match(email):
        found = sorted({ch for ch in email if ch.isspace() or ch in IMPOSSIBLE_CHARACTERS})
        if found:
            names = ", ".join(repr(ch) for ch in found)
            return f"The address contains {names}, which cannot be part of an email address."
        return "The address is not in the form name@example.com."
    if domain.rsplit(".", 1)[-1].isdigit():
        return "The domain must end in letters, not numbers."
    return None
