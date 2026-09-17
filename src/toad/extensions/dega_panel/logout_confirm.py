"""Explicit confirmation before clearing the local DEGA session."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class LogoutConfirm(ModalScreen[bool]):
    """Keep the session intact until the user confirms sign-out."""

    BINDINGS = [("escape", "cancel", "Cancel")]
    AUTO_FOCUS = "#cancel-logout"
    DEFAULT_CSS = """
    LogoutConfirm { align: center middle; }
    LogoutConfirm #logout-dialog {
        width: 54; max-width: 90%; height: auto;
        padding: 1 2; background: $surface; border: round $primary;
    }
    LogoutConfirm Label { width: 1fr; height: auto; margin-bottom: 1; }
    LogoutConfirm Horizontal { height: auto; align-horizontal: right; }
    LogoutConfirm Button { margin-left: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="logout-dialog"):
            yield Label("Sign out of DEGA?")
            yield Label("You will need to sign in again to access your account.")
            with Horizontal():
                yield Button("Cancel", id="cancel-logout")
                yield Button("Sign out", id="confirm-logout", variant="error")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-logout")
