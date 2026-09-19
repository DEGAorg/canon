"""Retirement affects catalogue selection without deleting installed projects."""

from unittest.mock import AsyncMock, Mock

import pytest

from toad.extensions.dega_panel.data import BUILDS, BUILDS_BY_KEY
from toad.extensions.dega_panel.runner import StrategyManifest
from toad.strategy_selection import available_strategies

RETAINED = {
    'arbiter', 'oracle-bot', 'prediction-edge', 'courtshock',
    'court-edge-arifin', 'market-forecast', 'nba-playoff-bot',
    'core-arb-binary', 'core-mint-01', 'core-mm-premium', 'core-trade-momentum',
}
RETIRED = ('ivee', 'oracle-shift', 'court-edge-referee', 'sentiment-squeeze', 'pred-market')


def test_catalogue_offers_approved_editable_templates():
    assert set(BUILDS_BY_KEY) == RETAINED
    assert len(BUILDS) == len(RETAINED)
    assert all('template' in build.summary.lower() for build in BUILDS)


@pytest.mark.asyncio
@pytest.mark.parametrize('key', RETIRED)
async def test_retired_installed_package_is_not_selected_or_modified(tmp_path, monkeypatch, key):
    source = tmp_path / key / 'src' / 'strategy.ts'
    source.parent.mkdir(parents=True)
    source.write_text('// user-edited source\n')
    installed = [key, 'arbiter']
    access = AsyncMock(return_value=None)
    detect = Mock(return_value=StrategyManifest(key='arbiter', path=tmp_path / 'arbiter'))
    monkeypatch.setattr('toad.strategy_selection.load_installed', lambda: installed)
    monkeypatch.setattr('toad.strategy_selection.ensure_access', access)
    monkeypatch.setattr('toad.strategy_selection.detect_manifest', detect)

    assert await available_strategies() == [
        {'key': 'arbiter', 'name': 'arbiter', 'path': str(tmp_path / 'arbiter')},
    ]
    access.assert_awaited_once_with('arbiter')
    detect.assert_called_once_with('arbiter')
    assert installed == [key, 'arbiter']
    assert source.read_text() == '// user-edited source\n'


def test_oracle_summary_describes_its_managed_dry_run_workflow():
    assert 'one-shot' not in BUILDS_BY_KEY['oracle-bot'].summary
