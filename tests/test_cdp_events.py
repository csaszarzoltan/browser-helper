"""
Interface + behavioral tests for CDPEventForwarder (src/cdp_events.py).

Interface tests verify the class contract, constructor signature, and
method signatures.
Behavioral tests confirm that calling any method raises ``NotImplementedError``.
"""

import inspect

import pytest

from src.cdp_events import CDPEventForwarder


# ---------------------------------------------------------------------------
# Interface tests
# ---------------------------------------------------------------------------


class TestCDPEventForwarderInterface:
    """Verify CDPEventForwarder class contract."""

    def test_module_importable(self):
        assert CDPEventForwarder.__module__ == "src.cdp_events"

    def test_constructor_signature(self):
        """Constructor accepts ``cdp_client`` and ``ws_manager``."""
        sig = inspect.signature(CDPEventForwarder.__init__)
        params = sig.parameters
        assert "cdp_client" in params
        assert "ws_manager" in params

    def test_start_async(self):
        """``start`` is an async method."""
        assert inspect.iscoroutinefunction(CDPEventForwarder.start)

    def test_stop_async(self):
        """``stop`` is an async method."""
        assert inspect.iscoroutinefunction(CDPEventForwarder.stop)

    def test_start_return_annotation(self):
        """``start`` returns None."""
        hints = inspect.get_annotations(CDPEventForwarder.start)
        assert hints.get("return") is None or "return" not in hints

    def test_stop_return_annotation(self):
        """``stop`` returns None."""
        hints = inspect.get_annotations(CDPEventForwarder.stop)
        assert hints.get("return") is None or "return" not in hints


# ---------------------------------------------------------------------------
# Behavioral tests  (expect NotImplementedError)
# ---------------------------------------------------------------------------


class TestCDPEventForwarderBehavior:
    """Confirm every stub raises ``NotImplementedError``."""

    @pytest.fixture
    def forwarder(self):
        """Create a CDPEventForwarder with None (mock) dependencies."""
        return CDPEventForwarder(cdp_client=None, ws_manager=None)

    @pytest.mark.asyncio
    async def test_start_raises(self, forwarder):
        with pytest.raises(NotImplementedError):
            await forwarder.start()

    @pytest.mark.asyncio
    async def test_stop_raises(self, forwarder):
        with pytest.raises(NotImplementedError):
            await forwarder.stop()
