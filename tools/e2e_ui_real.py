"""E2E de UI REAL: monta ProjectStatePane (como Canon), muestra DEGA y captura screenshot.

Reproduce el panel derecho real donde vive la pestaña DEGA. Monta el widget real
(no un harness aislado del DegaPane), abre la seccion DEGA y toma screenshots PNG
(texto) a un ancho de terminal configurable.
"""
import asyncio
import os

os.environ["DEGA_CHAT_BACKEND"] = "test"
os.environ.setdefault("DEGA_E2E_APP_WIDTH", "110")

from textual.app import App
from textual.containers import Vertical


class PaneHostApp(App):
    def compose(self):
        yield Vertical(id="pane-host")

    async def on_mount(self):
        from toad.widgets.project_state_pane import ProjectStatePane, SECTION_DEGA
        host = self.query_one("#pane-host", Vertical)
        self.pane = ProjectStatePane()
        await host.mount(self.pane)
        # diagnostico: se descubrio el panel DEGA?
        try:
            print("dega_panel:", self.pane._dega_panel)
        except Exception as exc:
            print("no dega_panel:", exc)
        # abrir la seccion DEGA (display=True dispara el worker _fetch_dega)
        try:
            sec = self.pane.query_one(f"#{SECTION_DEGA}")
            print("section-dega existe:", sec.id, "display:", sec.display)
            sec.display = True
            self._showed_dega = True
        except Exception as exc:
            self._showed_dega = False
            print(f"mostrar DEGA fallo: {exc}")


def dump_text(app, label):
    import re
    svg = app.export_screenshot()
    text = "".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
    text = text.replace("&#160;", " ").replace("&#x27;", "'")
    with open(f"/tmp/dega_e2e_{label}.svg", "w") as f:
        f.write(svg)
    with open(f"/tmp/dega_e2e_{label}.txt", "w") as f:
        f.write(text)
    print(f"  [{label}] chars={len(text)}")
    return text


async def main() -> int:
    width = int(os.environ.get("DEGA_E2E_APP_WIDTH", "110"))
    height = int(os.environ.get("DEGA_E2E_APP_HEIGHT", "45"))

    async def run_case(tag, width, height):
        class Host(PaneHostApp):
            pass

        async with Host().run_test(headless=True, size=(width, height)) as pilot:
            await pilot.pause(1.5)
            # forzar refresh del pane
            try:
                pilot.app.pane.refresh()
            except Exception:
                pass
            await pilot.pause(0.8)
            txt = dump_text(pilot.app, tag)
            return txt

    txt = await run_case("wide", width, height)
    print("--- CONTENIDO RENDERIZADO ---")
    # solo lineas no vacias
    lines = [l for l in txt.splitlines() if l.strip()]
    print("\n".join(lines[:40]))
    print("--- FIN ---")
    # verificar presencia de elementos clave
    checks = {
        "DEGA/Utility": any(k in txt for k in ["Utility", "Chat", "DEGA"]),
        "email/user": "pave" in txt.lower() or "dega.org" in txt.lower(),
        "elements": "Silver" in txt or "Obsidian" in txt or "Golden" in txt,
        "botones": "Logout" in txt or "locked" in txt.lower(),
    }
    print("--- CHECKS ---")
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'MISS'} {k}")
    return 0 if any(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))