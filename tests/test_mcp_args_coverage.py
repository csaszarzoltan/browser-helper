"""v1.36.8: the MCP integration smoke test must satisfy every tool's schema.

`TestHTTPE2E::test_every_tool_callable_over_http` walks `tools/list` and calls
each tool with synthetic arguments.  Its `_args_for` table had drifted badly:

* it keyed on SHORT names while `tools/list` returns fully-prefixed ones;
* it never covered the tools that declare REQUIRED parameters, so each of
  them died in pydantic validation (``Field required: url`` / ``action``)
  before the call could reach the envelope the test asserts on.

The authoritative source for those requirements is the registry's own schema
table, NOT the Python signatures — several tools (``dialog_handle``,
``rate_limiter_status``) are declared only there.  Deriving the requirement from
the same table the server builds its pydantic models from is what lets this
test catch a new tool that drifts uncovered.
"""

import mcp_server.tools as tools_mod
from mcp_server.registry import build_tool_defs


def _short(n: str) -> str:
    return n[len("browser_"):] if n.startswith("browser_") else n


def _tool_schemas() -> dict[str, list[str]]:
    """{tool_name: [required params]} from the registry's own schema table."""
    reg = build_tool_defs()
    out: dict[str, list[str]] = {}
    for d in reg._defs:
        params = d.parameters if isinstance(d.parameters, dict) else {}
        out[d.name] = list(params.get("required") or [])
    return out


def test_registry_declares_required_params():
    """Sanity: the schema table is actually reachable and populated."""
    schemas = _tool_schemas()
    assert len(schemas) == 75, f"expected 75 core tools, got {len(schemas)}"
    assert {k: v for k, v in schemas.items() if v}, (
        "no tool declares a required parameter — extraction is broken"
    )


def test_args_for_covers_every_required_param():
    """The core invariant: no tool may be called with a missing required arg."""
    from test_mcp_integration import _args_for

    missing: list[str] = []
    for full, required in sorted(_tool_schemas().items()):
        if not required:
            continue
        given = _args_for(full)
        for req in required:
            if req not in given:
                missing.append(f"{_short(full)} requires {req!r}, _args_for gave {given!r}")

    assert not missing, "required arguments not covered by _args_for:\n  " + "\n  ".join(missing)


def test_args_for_handles_prefixed_and_short_names():
    """Both transports' naming conventions must resolve to the same args."""
    from test_mcp_integration import _args_for

    for full, required in sorted(_tool_schemas().items()):
        if not required:
            continue
        for name in {full, _short(full)}:
            given = _args_for(name)
            for req in required:
                assert req in given, f"_args_for({name!r}) missing {req!r}"


def test_visual_diff_locale_is_excluded_from_the_smoke_test():
    """It launches Chrome and pixel-diffs per locale — not a smoke call."""
    from test_mcp_integration import HIGH_LEVEL_TOOLS

    assert "visual_diff_locale" in HIGH_LEVEL_TOOLS, (
        "browser_visual_diff_locale starts its own Chrome and navigates per "
        "locale; running it in the every-tool smoke test stalls the suite "
        "until the client times out."
    )


def test_core_tools_are_reachable():
    assert callable(getattr(tools_mod, "browser_navigate", None))
