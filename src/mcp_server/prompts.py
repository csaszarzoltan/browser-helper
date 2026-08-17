"""MCP server prompts — pre-built prompt templates for common workflows.

Provides prompt templates for competitive analysis, form automation,
and site monitoring workflows.
"""
from __future__ import annotations

from typing import Any


def competitive_analysis_prompt(topic: str, competitors: str) -> str:
    """Generate a competitive analysis workflow prompt.

    Args:
        topic: The topic or product area to analyze.
        competitors: Comma-separated list of competitor names.

    Returns:
        A prompt string describing the analysis workflow steps.
    """
    return (
        f"You are performing a competitive analysis of {topic}.\n\n"
        f"Competitors to analyze: {competitors}\n\n"
        "Workflow steps:\n"
        "1. Search for each competitor's product pages and documentation.\n"
        "2. Scrape pricing pages, feature lists, and product announcements.\n"
        "3. Extract key differentiators, pricing tiers, and unique selling points.\n"
        "4. Compare feature matrices across all competitors.\n"
        "5. Summarize findings with a recommendation matrix.\n\n"
        "Use the browser tools to navigate, search, observe, and extract data."
    )


def form_automation_prompt(target_url: str, form_fields: str) -> str:
    """Generate a form automation workflow prompt.

    Args:
        target_url: The URL containing the form to automate.
        form_fields: JSON string of field label/value pairs.

    Returns:
        A prompt string describing the form automation workflow steps.
    """
    return (
        f"You are automating form submission at {target_url}.\n\n"
        f"Form fields to fill:\n{form_fields}\n\n"
        "Workflow steps:\n"
        "1. Navigate to the target URL.\n"
        "2. Extract the form structure to identify field selectors.\n"
        "3. Fill each field with the provided values.\n"
        "4. Validate all required fields are filled.\n"
        "5. Submit the form and verify the response.\n\n"
        "Use the browser tools to navigate, observe, and act on form elements."
    )


def site_monitoring_prompt(url: str, check_interval: str) -> str:
    """Generate a site monitoring workflow prompt.

    Args:
        url: The URL to monitor.
        check_interval: How often to check (e.g., 'hourly', 'daily').

    Returns:
        A prompt string describing the site monitoring workflow steps.
    """
    return (
        f"You are setting up monitoring for {url}.\n\n"
        f"Check interval: {check_interval}\n\n"
        "Workflow steps:\n"
        "1. Navigate to the target URL.\n"
        "2. Take a snapshot of the page content and structure.\n"
        "3. Store the baseline snapshot for comparison.\n"
        "4. Configure the monitoring schedule.\n"
        "5. Set up alerting for content changes.\n\n"
        "Use the browser tools to navigate, snapshot, and store page state."
    )


def register_prompts(mcp: Any) -> None:
    """Register all prompt templates on a FastMCP server instance.

    Args:
        mcp: A FastMCP server instance.
    """
    from mcp.server.fastmcp.prompts.base import Prompt

    prompts_data = [
        (competitive_analysis_prompt, "competitive_analysis",
         "Competitive analysis workflow for product research"),
        (form_automation_prompt, "form_automation",
         "Automated form filling workflow"),
        (site_monitoring_prompt, "site_monitoring",
         "Website monitoring and change detection workflow"),
    ]
    for fn, name, description in prompts_data:
        prompt = Prompt.from_function(fn=fn, name=name, description=description)
        mcp.add_prompt(prompt)
