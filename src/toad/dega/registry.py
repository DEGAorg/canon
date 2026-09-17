"""Discover the DEGA panel from the extension module.

Canon TUI has no static dependency on ``toad.extensions.dega_panel``.
``discover()`` import-probes the module at runtime and returns its
``panel`` attribute when it satisfies :class:`DegaPanel`. All other
paths return ``None`` so the right-pane silently omits the section.
"""

from __future__ import annotations

import logging

from toad.dega.protocol import DegaPanel

_EXTENSION_MODULE = "toad.extensions.dega_panel"

logger = logging.getLogger(__name__)


def discover() -> DegaPanel | None:
    """Return the DEGA panel when available, else ``None``.

    Returns ``None`` when:

    - the ``toad.extensions.dega_panel`` submodule cannot be imported, OR
    - the module does not expose a ``panel`` attribute, OR
    - the panel does not satisfy :class:`DegaPanel` (missing manifest
      fields or lifecycle methods).
    """
    try:
        module = __import__(_EXTENSION_MODULE, fromlist=["panel"])
    except ImportError:
        logger.debug("DEGA extension not installed; panel disabled.")
        return None

    panel = getattr(module, "panel", None)
    if panel is None:
        logger.warning(
            "DEGA extension %s has no `panel` attribute; panel disabled.",
            _EXTENSION_MODULE,
        )
        return None

    if not isinstance(panel, DegaPanel):
        logger.warning(
            "DEGA extension panel does not satisfy DegaPanel; panel disabled."
        )
        return None

    return panel
