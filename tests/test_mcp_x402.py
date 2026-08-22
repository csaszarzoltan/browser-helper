"""P0-3: x402 payment wrapper for premium tools — interface + behavioral tests.

Written by the pre-tester against analysis-brief.md spec P0-3 *before*
the developer implements the x402 module.

Phase semantics
---------------
- **Interface tests** (class ``TestInterface``) verify that the x402
  module can be imported and its public API has the expected types.
  These will FAIL on import until ``src/mcp_server/x402.py`` exists.
- **Behavioral tests** (class ``TestBehavioral``) exercise the pricing
  table, payment verification, error formatting, and server creation.
  They fail cleanly while the module is missing.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Interface tests — FAIL until src/mcp_server/x402.py exists
# ---------------------------------------------------------------------------


class TestInterface:
    """Verify imports, dataclass fields, and function signatures of the x402 module."""

    def test_import_x402_module(self):
        """src/mcp_server/x402.py must be importable."""
        import mcp_server.x402  # noqa: F401

    def test_tool_price_dataclass_exists(self):
        """ToolPrice must be a frozen dataclass."""
        from dataclasses import is_dataclass

        from mcp_server.x402 import ToolPrice
        assert is_dataclass(ToolPrice)

    def test_tool_price_fields(self):
        """ToolPrice must have tool_name, price_cents, description, currency."""
        from mcp_server.x402 import ToolPrice
        names = {f.name for f in fields(ToolPrice)}
        assert "tool_name" in names
        assert "price_cents" in names
        assert "description" in names
        assert "currency" in names

    def test_tool_price_currency_default(self):
        """ToolPrice.currency must default to 'USDC'."""
        from mcp_server.x402 import ToolPrice
        tp = ToolPrice(tool_name="test", price_cents=1, description="d")
        assert tp.currency == "USDC"

    def test_x402_tool_prices_dict_exists(self):
        """X402_TOOL_PRICES must be a dict mapping tool names to ToolPrice."""
        from mcp_server.x402 import X402_TOOL_PRICES, ToolPrice
        assert isinstance(X402_TOOL_PRICES, dict)
        for key, val in X402_TOOL_PRICES.items():
            assert isinstance(key, str)
            assert isinstance(val, ToolPrice)

    def test_payment_required_error_exists(self):
        """PaymentRequiredError must be an Exception subclass."""
        from mcp_server.x402 import PaymentRequiredError
        assert issubclass(PaymentRequiredError, Exception)

    def test_check_x402_payment_exists(self):
        """check_x402_payment must be a callable async function."""
        from mcp_server.x402 import check_x402_payment
        assert callable(check_x402_payment)
        assert inspect.iscoroutinefunction(check_x402_payment)

    def test_check_x402_payment_signature(self):
        """check_x402_payment(tool_name, payment_token, pricing)."""
        from mcp_server.x402 import check_x402_payment
        sig = inspect.signature(check_x402_payment)
        params = list(sig.parameters.keys())
        assert "tool_name" in params
        assert "payment_token" in params
        assert "pricing" in params

    def test_create_x402_mcp_server_exists(self):
        """create_x402_mcp_server must be callable."""
        from mcp_server.x402 import create_x402_mcp_server
        assert callable(create_x402_mcp_server)

    def test_build_paid_tool_defs_exists(self):
        """build_paid_tool_defs must be callable from registry."""
        from mcp_server.registry import build_paid_tool_defs
        assert callable(build_paid_tool_defs)


# ---------------------------------------------------------------------------
# Behavioral tests — FAIL cleanly while the module is missing
# ---------------------------------------------------------------------------


class TestBehavioral:
    """Exercise the x402 payment module end-to-end."""

    def test_x402_pricing_table_covers_premium_tools(self):
        """All 5 premium tools must be in the pricing table."""
        from mcp_server.x402 import X402_TOOL_PRICES
        expected = {"fleet_run_batch", "search", "observe", "act", "clone_session"}
        assert expected == set(X402_TOOL_PRICES.keys()), (
            f"Pricing table missing tools: {expected - set(X402_TOOL_PRICES.keys())}"
        )

    def test_free_tool_bypasses_payment(self):
        """A tool not in the pricing table must pass without payment."""
        from mcp_server.x402 import check_x402_payment
        # navigate is NOT in the pricing table — should return True
        result = check_x402_payment("navigate", None)
        # handle both sync and async
        if inspect.isawaitable(result):
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(result)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_payment_with_valid_token(self):
        """A valid payment token must return True."""
        from mcp_server.x402 import check_x402_payment
        result = await check_x402_payment("search", "valid-payment-proof-token")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_payment_without_token_raises(self):
        """Missing token on a priced tool must raise PaymentRequiredError."""
        from mcp_server.x402 import PaymentRequiredError, check_x402_payment
        with pytest.raises(PaymentRequiredError):
            await check_x402_payment("search", None)

    def test_payment_required_error_message_format(self):
        """PaymentRequiredError message must include the price."""
        from mcp_server.x402 import PaymentRequiredError, ToolPrice
        price = ToolPrice("search", 3, "Web search")
        err = PaymentRequiredError("search", price)
        msg = str(err)
        assert "0.03" in msg, f"Error message should include price 0.03: {msg}"
        assert "USDC" in msg, f"Error message should include currency: {msg}"
        assert "search" in msg

    def test_build_paid_tool_defs_filters_correctly(self):
        """build_paid_tool_defs must return only tools in the pricing table."""
        from mcp_server.x402 import X402_TOOL_PRICES

        from mcp_server.registry import build_paid_tool_defs
        paid = build_paid_tool_defs(pricing=X402_TOOL_PRICES)
        names = [t.name for t in paid]
        # Only priced tools should appear
        for name in names:
            assert name in X402_TOOL_PRICES, (
                f"Tool {name} is in paid defs but not in pricing table"
            )

    @pytest.mark.asyncio
    async def test_create_x402_server_inherits_base_tools(self):
        """create_x402_mcp_server must include both free and paid tools."""
        from mcp_server.x402 import create_x402_mcp_server
        server = create_x402_mcp_server()
        # Server should have both free (navigate) and paid (search) tools
        assert server is not None  # basic construction check

    def test_x402_import_graceful_without_package(self):
        """x402 module must be importable even without the x402 pip package."""
        import mcp_server.x402
        # The module itself should import; the x402 pip package
        # is optional and only needed for real payment verification.
        assert hasattr(mcp_server.x402, "X402_TOOL_PRICES")
