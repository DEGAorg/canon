"""Original Core templates carry provenance without competition or activity claims."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from toad.extensions.dega_panel import utility
from toad.extensions.dega_panel.data import BUILDS, Build


@pytest.mark.asyncio
async def test_core_template_renders_without_invented_metadata(monkeypatch):
    build = Build(
        key="core-test", submission_id=None, name="Canon Core test",
        summary="Editable original Core template.", repo="", score=None, rule=None,
        markets=None, signals_24h=None, last_run=None, phase=None, origin="core",
    )
    monkeypatch.setattr(utility, "BUILDS", [build])
    monkeypatch.setattr(utility, "BUILDS_BY_KEY", {build.key: build})
    monkeypatch.setattr(utility, "is_installed", lambda key: False)
    eligibility = AsyncMock(return_value={"state": "unavailable", "alternatives": []})
    monkeypatch.setattr(utility, "backend_eligibility", eligibility)

    class Host(App):
        def compose(self) -> ComposeResult:
            yield utility.UtilityView(SimpleNamespace(elements={}))

    app = Host()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        row = str(app.query_one(".build-body", Static).render())
        detail = str(app.query_one("#detail-head", Static).render())
        assert "Curated Core template" in row and "Curated Core template" in detail
        assert "None" not in row + detail
        assert "0.00" not in row and "#" not in detail
        assert "Unable to check access" in str(app.query_one("#detail-rule", Static).render())
        table = app.query_one("#detail-table", DataTable)
        assert not table.display and table.row_count == 0


def test_existing_community_metadata_remains_present():
    community = [build for build in BUILDS if build.origin == "community"]
    assert len(community) == 7
    assert all(build.submission_id is not None and build.score is not None for build in community)


def test_curated_catalogue_contains_only_approved_core_packages():
    curated = [build for build in BUILDS if build.origin == "core"]
    assert {build.key for build in curated} == {
        "core-arb-binary", "core-mint-01", "core-mm-premium", "core-trade-momentum",
    }
    for build in curated:
        assert "Curated Core template" in build.summary
        assert build.submission_id is None and build.score is None
        assert build.markets is None and build.signals_24h is None
        assert build.last_run is None and build.phase is None
        assert not build.winner


def test_unconfigured_core_rule_is_absent_and_not_exported_as_open(tmp_path, monkeypatch):
    import json
    from toad.extensions.dega_panel import gating

    path = tmp_path / "gating.json"
    monkeypatch.setattr(gating, "DEFAULT_GATING_FILE", path)
    monkeypatch.setenv("DEGA_GATING_FILE", str(path))
    assert gating.rule_for("core-arb-binary") is None
    assert gating.rule_for("unknown-template") is None
    assert gating.rule_for("arbiter") is not None
    gating.save_defaults()
    rules = json.loads(path.read_text())["rules"]
    assert not any(key.startswith("core-") for key in rules)
    assert len(rules) == 7


def test_momentum_copy_limits_claims_to_candidates():
    momentum = next(build for build in BUILDS if build.key == "core-trade-momentum")
    assert "candidates" in momentum.summary
    assert "no risk approval or orders" in momentum.summary
    assert momentum.rule is None
