"""Typed chain registration status and renewal terms for Canon."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Registration:
    username: str
    owner: str
    opened_at: int
    expires_at: int
    member_count: int
    active: bool
    checked_at: int

    @property
    def expiry_label(self) -> str:
        """Return a compact, explicitly zoned date for the registration UI."""
        return datetime.fromtimestamp(self.expires_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True)
class RenewalQuote:
    registration: Registration
    fee: int
    duration: int
    decimals: int | None
    pending: bool = False
