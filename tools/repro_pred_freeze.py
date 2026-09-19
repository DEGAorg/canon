"""Headless repro: does running a prediction freeze the Utility view?

Mounts DegaPane, selects the prediction-edge build, triggers action_run_strategy,
confirms the _RunConfirm modal programmatically, and measures whether the app
event loop stays responsive while the subprocess runs.

Run:  uv run python tools/repro_pred_freeze.py
"""
from __future__ import annotations

import asyncio
import time
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import ListView
from toad.extensions.dega_panel.pane import DegaPane
from toad.extensions.dega_panel.utility import BuildRow


class HostHarness(App[None]):
    CSS = "Screen { overflow: hidden; }"

    def compose(self) -> ComposeResult:
        yield Vertical(id="container")


async def main() -> None:
    app = HostHarness()
    pane = DegaPane()
    async with app.run_test(size=(120, 40)) as pilot:
        await app.query_one("#container", Vertical).mount(pane)
        for _ in range(10):
            await pilot.pause()
        print("mounted ok; focusing build list")
        lst = pane.query_one("#build-list", ListView)
        names = [item.build.key for item in lst.query(BuildRow)]
        print("builds:", names)
        target = [i for i, k in enumerate(names) if k == "prediction-edge"]
        if not target:
            print("!! prediction-edge not in list")
            from toad.extensions.dega_panel import data
            return
        lst.index = target[0]
        for _ in range(5):
            await pilot.pause()

        heartbeats: list[float] = []
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                heartbeats.append(time.monotonic())
                await asyncio.sleep(0.02)

        hb = asyncio.create_task(heartbeat())

        t0 = time.monotonic()
        lst.focus()
        await pilot.press("r")
        for _ in range(60):
            await pilot.pause()
            if app.screen.__class__.__name__ == "_RunConfirm":
                break
        print("after press r -> screen:", app.screen.__class__.__name__,
              "elapsed", round(time.monotonic() - t0, 2))
        if app.screen.__class__.__name__ == "_RunConfirm":
            for b in app.screen.query("Button"):
                if b.id == "run":
                    b.press()
                    break
        t1 = time.monotonic()
        for _ in range(50):
            await pilot.pause()
        t2 = time.monotonic()
        stop.set()
        await hb
        duration = t2 - t1
        ticks = [t for t in heartbeats if t1 <= t <= t2]
        alive = len(ticks)
        print(f"run window {duration:.2f}s, heartbeat ticks in window={alive}")
        if alive == 0:
            print("!! EVENT LOOP FULLY STALLED during run (UI frozen)")
        elif alive < duration / 0.2:
            print("!! LOOP HEAVILY CONTENDED:", alive, "ticks")

        op = pane.query_one("#op-status")
        print("op-status:", op.render())


if __name__ == "__main__":
    asyncio.run(main())