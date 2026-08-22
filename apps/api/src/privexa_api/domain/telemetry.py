from __future__ import annotations

import logging

LOGGER = logging.getLogger("privexa.domain")
_HANDLER_NAME = "privexa-domain-json"


def configure_domain_logging() -> None:
    """Configure one content-free JSON-line logger for domain operation outcomes."""

    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
