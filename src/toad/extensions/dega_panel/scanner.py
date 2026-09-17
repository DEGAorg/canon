"""Security scanner for downloaded workflows.

The 2026-08-27 client requirement ("review with the AI so it has no
malicious code") is layered on top of the existing runner hardening
(``--ignore-scripts``, explicit ``_RunConfirm``, dry-run). This module scans
a strategy tree after install and flags code patterns that commonly allow a
third party to exfiltrate secrets or steal funds.

The checks are intentionally heuristic and non-blocking by default: they
surface a risk score + flagged files so a human (or a later LLM pass) can
decide. A high risk score does NOT auto-deny — a strategy is code someone
deliberately ran, so the scan is a guardrail, not a permission system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --- Signatures -------------------------------------------------------------

# Hosts that are legitimate (registries, public APIs, docs, standards bodies,
# donation links) and must NOT count as data exfiltration. A downloaded strategy
# referencing these is normal; flagging them produced thousands of false
# positives (npm registry, news, Polymarket/gamma/clob, docs, Mitre, etc.).
_EXFIL_ALLOW = {
    "registry.npmjs.org", "unpkg.com", "cdn.jsdelivr.net", "esm.sh", "github.com",
    "raw.githubusercontent.com", "gist.github.com", "npmjs.com", "www.npmjs.com",
    "yarnpkg.com", "itmycode.com", "nodejs.org", "api.github.com",
    "west.mit.edu", "www.w3.org", "developer.mozilla.org", "docs.python.org",
    "cryptography.io", "www.rfc-editor.org", "datatracker.ietf.org",
    "polymarket.com", "gamma-api.polymarket.com", "clob.polymarket.com",
    "docs.polymarket.com", "openbook.polymarket.com", "polygon.drpc.org",
    "rpc.polygon", "api.espn.com", "site.api.espn.com", "www.espn.com",
    "balldontlie.io", "feeds.bbci.co.uk", "news.google.com", "finance.yahoo.com",
    "www.cnbc.com", "upload.wikimedia.org", "en.wikipedia.org",
    "attack.mitre.org", "owasp.org", "example.com", "localhost",
    "play.google.com", "apps.apple.com", "vercel.app", "vercel.com",
    "opencollective.com", "www.buymeacoffee.com", "gitcoin.co", "tidelift.com",
    "www.patreon.com", "feross.org", "paulmillr.com", "dotenvx.com",
    "console.groq.com", "api.groq.com", "openrouter.ai", "googleapis.com",
    "fonts.googleapis.com", "fonts.gstatic.com", "gateway.pinata.cloud",
    "astral.sh", "docs.getfoundry.sh", "book.getfoundry.sh", "solc-bin.ethereum.org",
    "etherscan.io", "sepolia.etherscan.io", "uniswap.org", "app.uniswap.org",
    "www.coingecko.com", "api.coingecko.com", "scholar.google.com", "arxiv.org",
    "elifesciences.org", "www.media.mit.edu", "jupyternotebook", "anaconda.org",
    "www.britannica.com", "platform.openai.com", "api.openai.com",
    "anthropic.com", "api.anthropic.com", "console.cloud.google.com",
    "cloud.google.com", "firebase.google.com", "aws.amazon.com", "portal.aws.amazon.com",
    "newsapi.org", "alpha-vantage.co", "www.alphavantage.co", "finnhub.io",
    "www.finnhub.io", "tradingview.com", "api.twelvedata.com",
    "polygon-rpc.com", "polygon-rpc.celobte", "dorahacks.io", "youtu.be",
    "youtube.com", "www.youtube.com", "aistudio.google.com",
    "facebook.github.io", "paypal.me", "github.io",
}
_EXFIL_URL = re.compile(r"\b(?:https?|ws|wss)://(?!github\.com)[\w.-]+", re.I)
_PRIVATE_KEY = re.compile(
    # Real exfiltration: a secret being read AND sent somewhere, or an explicit
    # keystore/mnemonic secret (not a TS type/field name or a doc mention).
    r"process\.env\.(?:PRIVATE_KEY|PRIVATE|KEY|MNEMONIC|SEED|WALLET)"
    r"|keystore"
    r"|(?:private|seed|recovery)[\s_-]*phrase\s*[=:]"
    r"|mnemonic\s*(?:=|\beq\b)|secret\s*key\s*[=:]",
    re.I,
)
_LIFECYCLE_OVERRIDE = re.compile(
    r"\"?(?:preinstall|install|postinstall)\"?\s*:\s*\s*[\"']",
)
_OBFUSCATION = re.compile(
    r"\beval\(|\bexec(?:Sync)?\(|\bFunction\([^)]*\)(?:\.\w*)?\s*\("
    r"|atob\(|Buffer\.from\([^,]+,\s*['\"]base64['\"]\)",
)
_SHELL_CMD = re.compile(r"\b(?:child_process|exec|spawn)\.", re.I)
_READ_HOME = re.compile(r"\b(?:process\.env\.HOME|os\.path\.expanduser|~/)", re.I)
_IP_ADDR = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
# Local/loopback addresses are not exfiltration targets.
_IP_ALLOW = {"0.0.0.0", "127.0.0.1", "255.255.255.255", "8.8.8.8", "1.1.1.1"}


def _is_exfil_url(url: str) -> bool:
    """A non-localhost, non-allowlisted host is a potential exfiltration target.

    Allow checks both the exact host and any subdomain of an allowed domain
    (e.g. ``ivee-apps.vercel.app`` → allowed via ``vercel.app``), since a
    downloaded strategy linking its own deployed app or a dependency site is
    normal, not exfiltration.
    """
    if not url or "://" not in url:
        return False
    host = url.split("://")[1].split("/")[0].split(":")[0].strip(".").lower()
    if not host:
        return False
    # A literal IP is not a URL-exfiltration signal (raw_ip rule covers it).
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return False
    if host in _EXFIL_ALLOW:
        return False
    # subdomain of an allowlisted domain (a.b.allow → allowed via .allow)
    for base in _EXFIL_ALLOW:
        if host.endswith("." + base):
            return False
    return True


@dataclass
class Finding:
    """A single flagged pattern with its reasons."""

    path: str
    line: int | None  # 1-based, None if not line-resolvable
    rule: str
    snippet: str


@dataclass
class ScanResult:
    """Aggregate result for one downloaded strategy tree."""

    key: str
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def risk_score(self) -> int:
        """Ad-hoc score: exfil + secret reads dominate; each is a point."""
        rules_weights = {
            "exfil_url": 2,
            "private_key": 4,
            "lifecycle_override": 2,
            "obfuscation": 2,
            "shell_cmd": 1,
            "read_home": 1,
            "raw_ip": 1,
        }
        by_rule: dict[str, int] = {}
        for f in self.findings:
            by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        return sum(rules_weights.get(rule, 1) * min(n, 3) for rule, n in by_rule.items())

    @property
    def highest(self) -> list[str]:
        """Rules that triggered, deduped, in risk order."""
        order = ["private_key", "exfil_url", "obfuscation", "lifecycle_override",
                 "shell_cmd", "raw_ip", "read_home"]
        seen: set[str] = set()
        out: list[str] = []
        for rule in order:
            if rule in seen:
                continue
            if any(f.rule == rule for f in self.findings):
                out.append(rule)
                seen.add(rule)
        return out


_RULES = [
    ("exfil_url", _EXFIL_URL, {"score": 3}),
    ("private_key", _PRIVATE_KEY, {"score": 4}),
    ("lifecycle_override", _LIFECYCLE_OVERRIDE, {"score": 2}),
    ("obfuscation", _OBFUSCATION, {"score": 2}),
    ("shell_cmd", _SHELL_CMD, {"score": 1}),
    ("read_home", _READ_HOME, {"score": 1}),
    ("raw_ip", _IP_ADDR, {"score": 1}),
]


def _should_scan(name: str) -> bool:
    """Scan code-ish files, skip node_modules/binary/big assets."""
    if "/node_modules/" in name or name.endswith(".map"):
        return False
    low = name.lower()
    if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff2",
                     ".ttf", ".mp4", ".mp3", ".ogg", ".zip", ".tar", ".gz")):
        return False
    return True


def scan_strategy(root: Path, key: str = "") -> ScanResult:
    """Walk ``root`` and flag risky patterns. Pure, so it is headless-testable.

    ``key`` is only used for reporting; the real key comes from the caller.
    Returns a :class:`ScanResult` — never raises on a weird file.

    Does NOT follow symlinks: ``rglob`` would traverse a repo-installed link
    pointing outside the tree (e.g. at the user's ~/.ssh), both leaking its
    contents into the scan and reporting a misleading path. ``os.walk`` with
    the default ``followlinks=False`` avoids both.
    """
    import os

    result = ScanResult(key=key or root.name)
    if not root.is_dir():
        return result

    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if not path.is_file():
                continue  # never follow a symlink, regardless of target
            if path.is_symlink():
                continue
            rel = path.as_posix()
            if not _should_scan(rel):
                continue
            result.files_scanned += 1
            try:
                content = path.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                for rule, regex, _meta in _RULES:
                    if rule == "exfil_url":
                        m = regex.search(line)
                        if m and _is_exfil_url(m.group(0)):
                            result.findings.append(
                                Finding(path=rel, line=lineno, rule=rule,
                                        snippet=line.strip()[:120])
                            )
                        continue
                    if rule == "raw_ip":
                        m = regex.search(line)
                        if m and m.group(0) not in _IP_ALLOW:
                            result.findings.append(
                                Finding(path=rel, line=lineno, rule=rule,
                                        snippet=line.strip()[:120])
                            )
                        continue
                    if regex.search(line):
                        result.findings.append(
                            Finding(
                                path=rel,
                                line=lineno,
                                rule=rule,
                                snippet=line.strip()[:120],
                            )
                        )
    return result


def describe(result: ScanResult) -> str:
    """Human-readable summary, following the pane's status idioms."""
    if not result.findings:
        return f"{result.key}: scan clean ({result.files_scanned} files)"
    head = f"{result.key}: {len(result.findings)} flag(s) · risk {result.risk_score}"
    tags = ", ".join(result.highest) or "n/a"
    return f"{head} [{tags}]"


def scan_severity(result: ScanResult) -> str:
    """Map a scan to the pane's status severity: 'ok' | 'warn' | 'error'."""
    if not result.findings:
        return "ok"
    if result.risk_score >= 6:
        return "error"  # exfil/secret reads dominate
    if result.risk_score >= 3:
        return "warn"
    return "ok"