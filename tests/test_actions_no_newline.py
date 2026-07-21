"""
Tests asserting that _mk_cmd never produces newlines in --actions strings.

Rationale: Inkscape 1.x on macOS silently fails when --actions contains embedded
newlines. This is a structural invariant that must hold across all code paths.
See: docs/decisions/adr-inkscape-actions-single-string.md
"""

import tempfile
from pathlib import Path

import pytest

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
    """Pull the --actions=... value from the assembled command list."""
    for arg in cmd:
        if arg.startswith("--actions="):
            return arg[len("--actions="):]
    raise AssertionError(f"No --actions= found in cmd: {cmd}")


class TestNoNewlinesInActionsArg:
    """_mk_cmd must never produce \\n or \\r in the --actions string."""

    def test_select_only_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=["select-all"],
        )
        cmd = _mk_cmd(infile, args, None)
        actions = _extract_actions(cmd)
        assert "\n" not in actions, f"newline found in: {actions!r}"
        assert "\r" not in actions, f"carriage return found in: {actions!r}"

    def test_export_png_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.png"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=["select-all"],
            export=Export(type="png", out=str(out), dpi=300, area="drawing"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_export_pdf_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.pdf"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="pdf", out=str(out), area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_export_svg_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        out = tmp_path / "out.svg"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[],
            export=Export(type="svg", out=str(out), area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_many_actions_no_newline(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=[
                "select-all",
                "object-to-path",
                "path-simplify",
                "path-union",
                "select-clear",
            ],
        )
        cmd = _mk_cmd(infile, args, None)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_actions_joined_with_semicolon_only(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=["select-all", "object-to-path"],
        )
        cmd = _mk_cmd(infile, args, None)
        actions = _extract_actions(cmd)
        tokens = actions.split(";")
        for token in tokens:
            assert "\n" not in token
            # spaces only allowed inside colon-separated tokens (e.g. export-filename:/path with spaces)
            stripped = token.split(":", 1)[0]
            assert " " not in stripped

    def test_export_with_long_filename_no_newline(self, workspace, tmp_path):
        """Long filenames with path separators must not introduce newlines."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        out = deep / "output_with_long_name_that_might_wrap.png"
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=["select-all"],
            export=Export(type="png", out=str(out), area="page"),
        )
        cmd = _mk_cmd(infile, args, out)
        actions = _extract_actions(cmd)
        assert "\n" not in actions
        assert "\r" not in actions

    def test_actions_arg_is_single_string_element(self, workspace, tmp_path):
        """--actions must be a single list element, never split across multiple."""
        infile = tmp_path / "test.svg"
        infile.write_text("<svg/>")
        args = RunArgs(
            doc=Doc(type="file", path="test.svg"),
            actions=["select-all", "object-to-path"],
            export=Export(type="png", out=str(tmp_path / "out.png"), area="page"),
        )
        cmd = _mk_cmd(infile, args, tmp_path / "out.png")
        actions_args = [a for a in cmd if "--actions" in a]
        assert len(actions_args) == 1, "Exactly one --actions element expected"
        assert actions_args[0].startswith("--actions="), "Must use --actions= form"


