"""Discover the Growth panel from the private extension submodule.

Canon TUI has no static dependency on ``toad.extensions.dega_growth``.
``discover()`` import-probes the module at runtime and returns its
``panel`` attribute when it satisfies :class:`GrowthPanel`. All other
paths return ``None`` so the right-pane silently omits the section.
"""

from __future__ import annotations

import logging

from toad.growth.protocol import GrowthPanel

_EXTENSION_MODULE = "toad.extensions.dega_growth"

logger = logging.getLogger(__name__)


def discover() -> GrowthPanel | None:
    """Return the Growth panel when available, else ``None``.

    Returns ``None`` when:

    - the ``toad.extensions.dega_growth`` submodule cannot be imported, OR
    - the module does not expose a ``panel`` attribute, OR
    - the panel does not satisfy :class:`GrowthPanel` (missing manifest
      fields or lifecycle methods).
    """
    try:
        module = __import__(_EXTENSION_MODULE, fromlist=["panel"])
    except ImportError:
        logger.debug("Growth extension not installed; panel disabled.")
        return None

    panel = getattr(module, "panel", None)
    if panel is None:
        logger.warning(
            "Growth extension %s has no `panel` attribute; panel disabled.",
            _EXTENSION_MODULE,
        )
        return None

    if not isinstance(panel, GrowthPanel):
        logger.warning(
            "Growth extension panel does not satisfy GrowthPanel; panel disabled."
        )
        return None

    return panel
