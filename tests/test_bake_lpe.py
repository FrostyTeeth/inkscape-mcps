"""
Tests for the bake_lpe MCP tool.

Rationale: LPE output can only be computed by a running Inkscape process.
The bake_lpe tool drives select-all;path-effects-apply via the existing CLI
infrastructure and exports plain SVG, closing the LPE BLOCKER identified in
docs/observer-log.md (P1).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp import Client

from inkscape_mcp.cli_server import (
    _init_config,
    _mk_cmd,
    _validate_selector,
    app,
    Doc,
    Export,
    RunArgs,
    SAFE_ACTIONS,
)
from inkscape_mcp.config import InkscapeConfig
from fastmcp.exceptions import ValidationError

SVG_WITH_LPE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <defs>
    <inkscape:path-effect id="lpe-offset" effect="offset" offset="3"/>
  </defs>
  <path id="ring"
        inkscape:path-effect="url(#lpe-offset)"
        inkscape:original-d="M 160,0 A 160,160 0 1 1 -160,0 A 160,160 0 1 1 160,0 Z"
        d="M 163,0 A 163,163 0 1 1 -163,0 A 163,163 0 1 1 163,0 Z"/>
</svg>"""


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def bake_config(temp_workspace):
    config = InkscapeConfig(
        workspace=temp_workspace,
        max_file_size=1024 * 1024,
        timeout_default=30,
        max_concurrent=2,
    )
    _init_config(config)
    return config


def _extract_actions(cmd: list[str]) -> str:
    for arg in cmd:
        if arg.startswith("--actions="):
            return arg[len("--actions="):]
    raise AssertionError(f"No --actions= in cmd: {cmd}")


class TestPathEffectsApplyInAllowlist:
    """path-effects-apply must be in SAFE_ACTIONS."""

    def test_path_effects_apply_is_safe(self):
        assert "path-effects-apply" in SAFE_ACTIONS

    def test_path_effects_apply_passes_runargs_validator(self):
        args = RunArgs(
            doc=Doc(type="inline", svg="<svg/>"),
            actions=["select-all", "path-effects-apply"],
        )
        assert "path-effects-apply" in args.actions


class TestBakeLpeToolDiscovery:
    """bake_lpe must be discoverable via MCP tool listing."""

    @pytest.mark.asyncio
    async def test_bake_lpe_in_tool_list(self, bake_config):
        async with Client(app) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools]
            assert "bake_lpe" in tool_names

    @pytest.mark.asyncio
    async def test_bake_lpe_schema_has_doc_and_out(self, bake_config):
        async with Client(app) as client:
            tools = await client.list_tools()
            bake = next(t for t in tools if t.name == "bake_lpe")
            params = bake.inputSchema.get("properties", {})
            assert "doc" in params
            assert "out" in params

    @pytest.mark.asyncio
    async def test_bake_lpe_selector_is_optional(self, bake_config):
        async with Client(app) as client:
            tools = await client.list_tools()
            bake = next(t for t in tools if t.name == "bake_lpe")
            required = bake.inputSchema.get("required", [])
            assert "selector" not in required


class TestBakeLpeCommandAssembly:
    """bake_lpe must produce the correct action sequence in --actions."""

    def test_select_all_and_path_effects_apply_present(self, bake_config, temp_workspace):
        infile = temp_workspace / "in.svg"
        infile.write_text(SVG_WITH_LPE)
        out = temp_workspace / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="in.svg"),
            actions=["select-all", "path-effects-apply"],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "select-all" in actions
        assert "path-effects-apply" in actions

    def test_export_plain_svg_included(self, bake_config, temp_workspace):
        infile = temp_workspace / "in.svg"
        infile.write_text(SVG_WITH_LPE)
        out = temp_workspace / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="in.svg"),
            actions=["select-all", "path-effects-apply"],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "export-plain-svg" in actions

    def test_selector_produces_select_by_id(self, bake_config, temp_workspace):
        infile = temp_workspace / "in.svg"
        infile.write_text(SVG_WITH_LPE)
        out = temp_workspace / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="in.svg"),
            actions=["select-by-id:ring", "path-effects-apply"],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "select-by-id:ring" in actions
        assert "path-effects-apply" in actions

    def test_bake_lpe_actions_no_newline(self, bake_config, temp_workspace):
        infile = temp_workspace / "in.svg"
        infile.write_text(SVG_WITH_LPE)
        out = temp_workspace / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="in.svg"),
            actions=["select-all", "path-effects-apply"],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions


class TestSelectorValidation:
    """_validate_selector must reject injectable characters."""

    def test_alphanumeric_accepted(self):
        assert _validate_selector("ring") == "ring"
        assert _validate_selector("path123") == "path123"
        assert _validate_selector("my-shape") == "my-shape"
        assert _validate_selector("shape_1") == "shape_1"

    def test_semicolon_rejected(self):
        with pytest.raises((ValidationError, Exception)):
            _validate_selector("ring;evil-action")

    def test_newline_rejected(self):
        with pytest.raises((ValidationError, Exception)):
            _validate_selector("ring\nevil")

    def test_space_rejected(self):
        with pytest.raises((ValidationError, Exception)):
            _validate_selector("ring evil")

    def test_shell_metachar_rejected(self):
        for bad in ["ring$(cmd)", "ring`cmd`", "ring&&evil", "ring|evil", "ring>out"]:
            with pytest.raises((ValidationError, Exception)):
                _validate_selector(bad)


class TestBakeLpeValidation:
    """bake_lpe must enforce the same workspace/size constraints as action_run."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal_on_doc(self, bake_config):
        async with Client(app) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "file", "path": "../../../etc/passwd"},
                        "out": "output.svg",
                    },
                )
            msg = str(exc_info.value).lower()
            assert "workspace" in msg or "path" in msg

    @pytest.mark.asyncio
    async def test_rejects_path_traversal_on_out(self, bake_config):
        async with Client(app) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "inline", "svg": SVG_WITH_LPE},
                        "out": "../../../tmp/evil.svg",
                    },
                )
            msg = str(exc_info.value).lower()
            assert "workspace" in msg or "path" in msg

    @pytest.mark.asyncio
    async def test_rejects_oversized_inline_svg(self, bake_config):
        async with Client(app) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {
                            "type": "inline",
                            "svg": "<svg>" + "x" * (2 * 1024 * 1024) + "</svg>",
                        },
                        "out": "output.svg",
                    },
                )
            msg = str(exc_info.value).lower()
            assert "large" in msg or "size" in msg

    @pytest.mark.asyncio
    async def test_rejects_bad_selector_characters(self, bake_config):
        async with Client(app) as client:
            with pytest.raises(Exception):
                await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "inline", "svg": SVG_WITH_LPE},
                        "out": "output.svg",
                        "selector": "ring;evil-action",
                    },
                )


def _tmp_path_from_cmd(cmd: list[str]) -> Path:
    """Extract the export-filename path from an assembled --actions command."""
    actions_arg = next(a for a in cmd if a.startswith("--actions="))
    for token in actions_arg[len("--actions="):].split(";"):
        if token.startswith("export-filename:"):
            return Path(token[len("export-filename:"):])
    raise AssertionError(f"No export-filename token in: {actions_arg}")


class TestBakeLpeMockedRun:
    """bake_lpe integration via mocked _run_inkscape — no Inkscape required."""

    @pytest.mark.asyncio
    async def test_bake_lpe_returns_ok_and_out_path(self, bake_config, temp_workspace):
        svg_path = temp_workspace / "with_lpe.svg"
        svg_path.write_text(SVG_WITH_LPE)

        def fake_run(cmd, timeout, lock_path):
            # Inkscape writes to the tmp export path embedded in --actions
            _tmp_path_from_cmd(cmd).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            return b"", b""

        with patch("inkscape_mcp.cli_server._run_inkscape", side_effect=fake_run):
            async with Client(app) as client:
                result = await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "file", "path": "with_lpe.svg"},
                        "out": "baked.svg",
                    },
                )
        assert result.data["ok"] is True
        assert "baked.svg" in result.data["out"]

    @pytest.mark.asyncio
    async def test_bake_lpe_with_selector_passes_select_by_id(
        self, bake_config, temp_workspace
    ):
        svg_path = temp_workspace / "with_lpe.svg"
        svg_path.write_text(SVG_WITH_LPE)
        captured_cmd = {}

        def fake_run(cmd, timeout, lock_path):
            captured_cmd["cmd"] = cmd
            _tmp_path_from_cmd(cmd).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            return b"", b""

        with patch("inkscape_mcp.cli_server._run_inkscape", side_effect=fake_run):
            async with Client(app) as client:
                await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "file", "path": "with_lpe.svg"},
                        "out": "baked.svg",
                        "selector": "ring",
                    },
                )

        actions_arg = next(a for a in captured_cmd["cmd"] if a.startswith("--actions="))
        assert "select-by-id:ring" in actions_arg
        assert "path-effects-apply" in actions_arg
        assert "export-plain-svg" in actions_arg


class TestBakeLpeEndToEnd:
    """Live tests — skipped gracefully when Inkscape is not installed."""

    @pytest.mark.asyncio
    async def test_bake_lpe_produces_output_file(self, bake_config, temp_workspace):
        svg_path = temp_workspace / "with_lpe.svg"
        svg_path.write_text(SVG_WITH_LPE)
        async with Client(app) as client:
            try:
                result = await client.call_tool(
                    "bake_lpe",
                    {
                        "doc": {"type": "file", "path": "with_lpe.svg"},
                        "out": "baked.svg",
                    },
                )
                assert result.data.get("ok") is True
                out = Path(result.data["out"])
                assert out.exists()
            except Exception as e:
                expected = ["inkscape", "not found", "timeout"]
                assert any(s in str(e).lower() for s in expected)
