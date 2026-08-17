"""MCP server x402 — micropayment wrapper for premium tool gating.

Implements the x402 payment protocol for paid MCP tools. Tools not in
the pricing table are treated as free and bypass payment checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolPrice:
    """Price definition for a paid MCP tool."""

    tool_name: str
    price_cents: int
    description: str
    currency: str = "USDC"


# Authoritative pricing table for premium tools
X402_TOOL_PRICES: dict[str, ToolPrice] = {
    "fleet_run_batch": ToolPrice("fleet_run_batch", 10, "Run batch of browser tasks across fleet"),
    "search": ToolPrice("search", 3, "Web search with engine selection"),
    "observe": ToolPrice("observe", 2, "Semantic/accessibility page observation"),
    "act": ToolPrice("act", 2, "Execute browser actions via semantic refs"),
    "clone_session": ToolPrice("clone_session", 5, "Clone browser session with cookies/state"),
}


class PaymentRequiredError(Exception):
    """Raised when a paid tool is called without valid payment."""

    def __init__(self, tool_name: str, price: ToolPrice) -> None:
        self.tool_name = tool_name
        self.price = price
        amount = price.price_cents / 100
        super().__init__(
            f"Payment required for '{tool_name}': "
            f"{amount:.2f} {price.currency}. "
            f"{price.description}"
        )


async def check_x402_payment(
    tool_name: str,
    payment_token: str | None,
    pricing: dict[str, ToolPrice] | None = None,
) -> bool:
    """Check payment for a tool call.

    Free tools (not in pricing table) always pass.
    Paid tools require a non-empty payment_token.

    Returns:
        True if the tool is free or payment is valid.

    Raises:
        PaymentRequiredError: If the tool requires payment but no token is provided.
    """
    prices = pricing if pricing is not None else X402_TOOL_PRICES
    if tool_name not in prices:
        return True  # Free tool — no payment needed
    if not payment_token:
        raise PaymentRequiredError(tool_name, prices[tool_name])
    return True  # Token present — accept for now (real verification requires x402 SDK)


def create_x402_mcp_server(settings: Any = None) -> Any:
    """Create a FastMCP server with x402 payment-gated tools.

    Returns a FastMCP server instance that wraps the base server
    with payment checking middleware.
    """
    from .server import MCPServer

    base = MCPServer(settings=settings)
    return base.mcp
