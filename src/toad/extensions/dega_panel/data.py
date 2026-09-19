"""Data for the DEGA panel (real catalogue + gating config).

Backend-shaped: the aggregation key is `${class}_${blessing || power || "default"}`
capitalised, so element class keys read "Silver Fire", "Golden Water". Access
rules are modelled as a JSON feature flag, which the backend already supports
(and which `gating.py` reads at runtime for per-build overrides).

Community builds retain their original submission scores; curated Core templates
have no competition or activity metadata and no local default access price.
Backend eligibility remains authoritative. They are editable templates,
not validated trading automations; submission metadata is not runtime evidence.
``repo`` points at our own file server (DEGAorg/canon-strategies)
so installs never depend on third-party GitHub repos that could change or
vanish. Element counts and thresholds are placeholders until DEGA confirms
the real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# --- Mocked /elements-aggregation/by-email response ------------------------

USER_EMAIL = "pavelespitia@gmail.com"
USER_ADDRESSES = [
    "0x1234567890abcdef1234567890abcdef12345678",
    "0xfedcba0987654321fedcba0987654321fedcba09",
]

# Stable order for rendering and for the 1/2/3 keys.
ELEMENT_KEYS = ["Silver Fire", "Golden Water", "Obsidian Earth"]


# --- Access rules (what would live in a JSON feature flag) -----------------


@dataclass(frozen=True)
class Rule:
    """Ownership thresholds. All of them must be met."""

    total: int = 0
    per_element: dict = field(default_factory=dict)

    def unmet(self, held: dict[str, int]) -> list[str]:
        """What is still missing. An empty list means unlocked."""
        missing: list[str] = []
        if self.total:
            have = sum(held.values())
            if have < self.total:
                missing.append(f"{self.total - have} more")
        for key, need in self.per_element.items():
            # Holdings are aggregated as "<Class> <blessing|power|Default>" (e.g.
            # "Obsidian earth Default"); a rule named by class alone must count
            # every holding whose key starts with that class, case-insensitively.
            base = key.lower()
            have = sum(
                v
                for k, v in held.items()
                if k.lower() == base or k.lower().startswith(base + " ")
            )
            if have < need:
                missing.append(f"{need - have} x {key}")
        return missing

    def describe(self) -> str:
        parts: list[str] = []
        if self.total:
            parts.append(f"total >= {self.total}")
        parts += [f"{k} >= {v}" for k, v in self.per_element.items()]
        return "  ".join(parts) if parts else "open"


@dataclass(frozen=True)
class Build:
    """An editable template with optional competition metadata and source origin."""

    key: str
    submission_id: int | None
    name: str
    summary: str
    repo: str
    score: float | None
    rule: Rule | None
    markets: int | None
    signals_24h: int | None
    last_run: str | None
    phase: int | None
    winner: bool = False
    origin: Literal["community", "core"] = "community"


BUILDS: list[Build] = [
    Build(
        "arbiter",
        44113,
        "Arbiter",
        "Editable template for market-coherence checks across related outcomes.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/arbiter.tar.gz",
        6.94,
        Rule(total=10, per_element={"Obsidian Earth": 5}),
        27,
        11,
        "12 min ago",
        5,
    ),

    Build(
        "oracle-bot",
        44077,
        "NBA Oracle Bot",
        "Editable NBA template with three signal engines and a dry-run workflow.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/oracle-bot.tar.gz",
        6.32,
        Rule(per_element={"Obsidian Earth": 3}),
        18,
        6,
        "1 h ago",
        5,
    ),

    Build(
        "prediction-edge",
        44122,
        "NBA Prediction Edge",
        "Editable template for injury signals and cross-market momentum research.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/prediction-edge.tar.gz",
        5.79,
        Rule(per_element={"Golden Water": 2}),
        22,
        9,
        "25 min ago",
        5,
        winner=True,
    ),

    Build(
        "courtshock",
        44014,
        "CourtShock AI",
        "Editable player-impact and fair-value template; feed integration needs development.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/courtshock.tar.gz",
        5.64,
        Rule(total=1),
        9,
        3,
        "6 h ago",
        4,
    ),

    Build(
        "court-edge-arifin",
        44084,
        "CourtEdge (arifintahu)",
        "Editable template for game polling, edge estimates, and dry-run risk checks.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/court-edge-arifin.tar.gz",
        5.25,
        Rule(per_element={"Silver Fire": 1}),
        8,
        2,
        "1 d ago",
        4,
    ),

    Build(
        "market-forecast",
        44083,
        "NBAMarketForecast",
        "Editable template for NBA forecasting and cross-venue research.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/market-forecast.tar.gz",
        4.73,
        Rule(total=1),
        7,
        2,
        "2 d ago",
        3,
    ),

    Build(
        "nba-playoff-bot",
        43899,
        "NBA play off",
        "Editable template for playoff probabilities; market mapping needs development.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/nba-playoff-bot.tar.gz",
        3.61,
        Rule(per_element={"Obsidian Earth": 2}),
        4,
        2,
        "3 d ago",
        3,
    ),
    Build(
        key="core-arb-binary",
        submission_id=None,
        name="Canon Core Binary Arbitrage",
        summary="Curated Core template for binary-book arbitrage scans and paper risk evaluation.",
        repo="https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/core-arb-binary.tar.gz",
        score=None,
        rule=None,
        markets=None,
        signals_24h=None,
        last_run=None,
        phase=None,
        origin="core",
    ),

    Build(
        key="core-mint-01",
        submission_id=None,
        name="Canon Core Mint-01",
        summary="Curated Core template for mint candidate selection and planned legs; no mints or fills.",
        repo="https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/core-mint-01.tar.gz",
        score=None,
        rule=None,
        markets=None,
        signals_24h=None,
        last_run=None,
        phase=None,
        origin="core",
    ),

    Build(
        key="core-mm-premium",
        submission_id=None,
        name="Canon Core MM Premium",
        summary="Curated Core template for public-data confluence scans and planned paper orders.",
        repo="https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/core-mm-premium.tar.gz",
        score=None,
        rule=None,
        markets=None,
        signals_24h=None,
        last_run=None,
        phase=None,
        origin="core",
    ),

    Build(
        key="core-trade-momentum",
        submission_id=None,
        name="Canon Core Trade Momentum",
        summary="Curated Core template for public-data momentum candidates; no risk approval or orders.",
        repo="https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/core-trade-momentum.tar.gz",
        score=None,
        rule=None,
        markets=None,
        signals_24h=None,
        last_run=None,
        phase=None,
        origin="core",
    ),

]
BUILDS_BY_KEY = {b.key: b for b in BUILDS}
