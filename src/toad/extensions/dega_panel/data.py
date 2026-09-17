"""Data for the DEGA panel (real catalogue + gating config).

Backend-shaped: the aggregation key is `${class}_${blessing || power || "default"}`
capitalised, so element class keys read "Silver Fire", "Golden Water". Access
rules are modelled as a JSON feature flag, which the backend already supports
(and which `gating.py` reads at runtime for per-build overrides).

Builds, scores and repos are the real workflow results (ranked by combined
score). ``repo`` points at our own file server (DEGAorg/canon-strategies)
so installs never depend on third-party GitHub repos that could change or
vanish. Element counts and thresholds are placeholders until DEGA confirms
the real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


PHASES = ["init", "scaffold", "strategy", "develop", "run", "live"]


@dataclass(frozen=True)
class Build:
    """A strategy workflow, candidate for absorption."""

    key: str
    submission_id: int
    name: str
    summary: str
    repo: str
    score: float
    rule: Rule
    markets: int
    signals_24h: int
    last_run: str
    phase: int
    winner: bool = False


BUILDS: list[Build] = [
    Build(
        "arbiter",
        44113,
        "Arbiter",
        "Does not try to predict the winner: it enforces the coherence the market "
        "forgot. P(champion) can never exceed P(conference), nor that P(series).",
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
        "Three signal engines running in parallel over a single Canon-orchestrated "
        "decision layer.",
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
        "Combines real-time injury intelligence with cross-market momentum lag on "
        "Polymarket, executing on speed.",
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
        "ivee",
        44117,
        "Ivee apps",
        "Automation dashboard built on Canon CLI, with a deployed demo and a demo "
        "script included.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/ivee.tar.gz",
        5.78,
        Rule(per_element={"Silver Fire": 2}),
        14,
        4,
        "3 h ago",
        4,
    ),

    Build(
        "courtshock",
        44014,
        "CourtShock AI",
        "Analyses six independent factors and computes fair value in real time, to "
        "enter before the price corrects.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/courtshock.tar.gz",
        5.64,
        Rule(total=1),
        9,
        3,
        "6 h ago",
        4,
    ),

    Build(
        "pred-market",
        43767,
        "nba-prediction-market",
        "NBA prediction market strategy with a focus on playoff pricing.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/pred-market.tar.gz",
        5.48,
        Rule(per_element={"Golden Water": 1}),
        10,
        3,
        "1 d ago",
        4,
    ),

    Build(
        "court-edge-arifin",
        44084,
        "CourtEdge (arifintahu)",
        "Court-edge detection model balancing momentum and line movement.",
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
        "Forecast-driven NBA market model with a long-horizon bias.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/market-forecast.tar.gz",
        4.73,
        Rule(total=1),
        7,
        2,
        "2 d ago",
        3,
    ),

    Build(
        "oracle-shift",
        44119,
        "OracleShift",
        "Shifts between signal engines based on regime detection.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/oracle-shift.tar.gz",
        3.94,
        Rule(per_element={"Obsidian Earth": 1}),
        5,
        1,
        "2 d ago",
        3,
    ),

    Build(
        "nba-playoff-bot",
        43899,
        "NBA play off",
        "Playoff series prediction bot tracking series-level probabilities.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/nba-playoff-bot.tar.gz",
        3.61,
        Rule(per_element={"Obsidian Earth": 2}),
        4,
        2,
        "3 d ago",
        3,
    ),

    Build(
        "court-edge-referee",
        43968,
        "CourtEdge (referee)",
        "Referencial court-edge model variant.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/court-edge-referee.tar.gz",
        3.36,
        Rule(per_element={"Golden Water": 1}),
        3,
        1,
        "3 d ago",
        2,
    ),

    Build(
        "sentiment-squeeze",
        43987,
        "Sentiment Squeeze",
        "Sentiment-driven buy/sell bot for DEGA prediction markets.",
        "https://raw.githubusercontent.com/DEGAorg/canon-strategies/main/sentiment-squeeze.tar.gz",
        2.74,
        Rule(per_element={"Silver Fire": 1}),
        2,
        1,
        "4 d ago",
        2,
    ),
]
BUILDS_BY_KEY = {b.key: b for b in BUILDS}
