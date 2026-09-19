from textual.app import ComposeResult
from textual import containers

from textual.widgets import Label, Markdown


ASCII_LOGO = r"""
   ____
  / ___|__ _ _ __   ___  _ __
 | |   / _` | '_ \ / _ \| '_ \
 | |__| (_| | | | | (_) | | | |
  \____\__,_|_| |_|\___/|_| |_|
"""


WELCOME_MD = """\
## Canon v1.0

Welcome!


"""


class Welcome(containers.Vertical):
    def compose(self) -> ComposeResult:
        with containers.Center():
            yield Label(ASCII_LOGO, id="logo")
        yield Markdown(WELCOME_MD, id="message", classes="note")
