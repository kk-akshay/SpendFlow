"""User-confirmed display names for exact UPI handles or bank payee references.

Bank narrations are not identities by themselves. Only apply a rule to a
high-confidence, stable payee reference; never use the transaction reference.
Rules affect future imports for this user only and never alter the raw statement.
"""
from __future__ import annotations

import re

from .merchants import merchant_key
from .people import upi_ids

# Structured UPI bank narration: UPI/<transaction ref>/Dr/<payee>/<bank>/<payee token>
# Do not use the per-transaction reference (which changes on each payment).
_BANK_REF = re.compile(
    r"(?i)^UPI[/|][0-9]{8,20}[/|](?:DR|CR)[/|][^/|]{2,80}[/|]"
    r"([A-Z]{4,8})[/|]([A-Z0-9._-]{6,80})(?:[/|]|$)"
)


def identity_details(description: str) -> dict | None:
    handles = upi_ids(description)
    if len(handles) == 1:
        return {"identity": "upi:" + handles[0], "kind": "upi",
                "label": "UPI ID: " + handles[0]}
    if len(handles) > 1:
        # Ambiguous payments can include both sender and receiver identifiers.
        return None
    match = _BANK_REF.match((description or "").strip())
    if match:
        bank, token = match.group(1).lower(), match.group(2).lower()
        if re.search("[a-z]", token) and token not in ("unknown", "payment", "transfer"):
            return {"identity": f"bankref:{bank}:{token}", "kind": "bank_reference",
                    "label": f"Bank payee reference: {bank.upper()} / {token}"}
    return None


def learn(db, user_id: int, identity: str, name: str):
    db.execute(
        "INSERT INTO payee_name_rules(user_id,identity,name) VALUES(?,?,?) "
        "ON CONFLICT(user_id,identity) DO UPDATE SET name=excluded.name",
        (user_id, identity, name))


def all_rules(db, user_id: int) -> dict[str, str]:
    return {r["identity"]: r["name"] for r in db.execute(
        "SELECT identity,name FROM payee_name_rules WHERE user_id=?", (user_id,))}


def renamed_fields(row: dict, rules: dict[str, str]) -> tuple[str, str]:
    name = row.get("merchant") or ""
    info = identity_details(row.get("description") or "")
    if info and info["identity"] in rules:
        name = rules[info["identity"]]
    return name, merchant_key(name)
