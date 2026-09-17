"""DEGA right-pane panel: element-gated utility and P2P chat.

The host discovers this module by import-probing `toad.extensions.dega_panel`
and reading the module-level `panel`. See `toad.dega.registry`.
"""

from toad.extensions.dega_panel.pane import DegaPanelImpl

panel = DegaPanelImpl()

__all__ = ["panel"]
