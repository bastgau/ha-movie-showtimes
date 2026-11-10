"""Fixtures of the client tests: they run without Home Assistant."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override the repository-wide fixture, which would start Home Assistant for every client test."""
