"""
Tests for the Export.plain field that emits export-plain-svg in the --actions string.

Rationale: --export-plain-svg as a standalone CLI flag is a legacy 0.9x form that
Inkscape may deprecate. The in-actions form (export-plain-svg token) is the idiomatic
Inkscape 1.x approach. See: docs/decisions/adr-inkscape-actions-single-string.md
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from inkscape_mcp.cli_server import (
    _init_config,
    _mk_cmd,
    Doc,
    Export,
    RunArgs,
)
from inkscape_mcp.config import InkscapeConfig


@pytest.fixture
def workspace(tmp_path):
    config = InkscapeConfig(workspace=tmp_path, max_file_size=1024 * 1024)
    _init_config(config)
    return tmp_path


def _extract_actions(cmd: list[str]) -> str:
    for arg in cmd:
        if arg.startswith("--actions="):
            return arg[len("--actions="):]
    raise AssertionError(f"No --actions= in: {cmd}")


class TestExportModelPlainField:
    """Export model must accept and validate the plain field."""

    def test_plain_defaults_to_false(self):
        e = Export(type="svg", out="out.svg")
        assert e.plain is False

    def test_plain_true_accepted_for_svg(self):
        e = Export(type="svg", out="out.svg", plain=True)
        assert e.plain is True

    def test_plain_true_rejected_for_png(self):
        with pytest.raises((PydanticValidationError, ValueError)) as exc_info:
            Export(type="png", out="out.png", plain=True)
        assert "plain" in str(exc_info.value).lower() or "svg" in str(exc_info.value).lower()

    def test_plain_true_rejected_for_pdf(self):
        with pytest.raises((PydanticValidationError, ValueError)) as exc_info:
            Export(type="pdf", out="out.pdf", plain=True)
        assert "plain" in str(exc_info.value).lower() or "svg" in str(exc_info.value).lower()

    def test_plain_false_accepted_for_all_types(self):
        for t, ext in [("png", "png"), ("pdf", "pdf"), ("svg", "svg")]:
            e = Export(type=t, out=f"out.{ext}", plain=False)
            assert e.plain is False


class TestMkCmdPlainSvg:
    """_mk_cmd must emit export-plain-svg action token when export.plain=True."""

    def test_plain_true_inserts_export_plain_svg_action(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "export-plain-svg" in actions

    def test_plain_false_does_not_insert_export_plain_svg(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=False, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "export-plain-svg" not in actions

    def test_plain_svg_token_appears_before_export_do(self, workspace, tmp_path):
        """export-plain-svg must precede export-do in the action sequence."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        tokens = _extract_actions(cmd).split(";")
        plain_idx = next((i for i, t in enumerate(tokens) if t == "export-plain-svg"), -1)
        do_idx = next((i for i, t in enumerate(tokens) if t == "export-do"), -1)
        assert plain_idx != -1, "export-plain-svg not found"
        assert do_idx != -1, "export-do not found"
        assert plain_idx < do_idx, "export-plain-svg must precede export-do"

    def test_plain_svg_no_standalone_flag_in_cmd(self, workspace, tmp_path):
        """Legacy --export-plain-svg standalone flag must NOT appear in the command list."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        assert "--export-plain-svg" not in cmd

    def test_plain_svg_action_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=True, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_non_plain_svg_export_unchanged(self, workspace, tmp_path):
        """Regular SVG export (plain=False) must produce the same actions as before."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=False, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "export-type:svg" in actions
        assert "export-do" in actions
        assert "export-plain-svg" not in actions

    def test_plain_svg_with_dpi_ignored(self, workspace, tmp_path):
        """DPI is ignored for SVG exports but must not interfere with plain token."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), plain=True, dpi=300, area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "export-plain-svg" in actions
        assert "export-do" in actions


class TestMCPActionRunPlainSvg:
    """action_run must accept plain=True in the export parameter via MCP."""

    @pytest.mark.asyncio
    async def test_action_run_accepts_plain_svg_export(self, workspace, tmp_path):
        from fastmcp import Client
        from inkscape_mcp.cli_server import app

        svg_file = tmp_path / "test.svg"
        svg_file.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        async with Client(app) as client:
            try:
                result = await client.call_tool(
                    "action_run",
                    {
                        "doc": {"type": "file", "path": "test.svg"},
                        "export": {"type": "svg", "out": "out.svg", "plain": True},
                    },
                )
                assert isinstance(result.data, dict)
            except Exception as e:
                expected = ["inkscape", "not found", "timeout"]
                assert any(s in str(e).lower() for s in expected)

    @pytest.mark.asyncio
    async def test_action_run_rejects_plain_true_with_png(self, workspace, tmp_path):
        from fastmcp import Client
        from inkscape_mcp.cli_server import app

        async with Client(app) as client:
            with pytest.raises(Exception) as exc_info:
                await client.call_tool(
                    "action_run",
                    {
                        "doc": {"type": "inline", "svg": "<svg/>"},
                        "export": {"type": "png", "out": "out.png", "plain": True},
                    },
                )
            assert exc_info.value is not None
