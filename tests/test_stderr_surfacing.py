"""
Tests verifying that Inkscape stderr is surfaced in error messages and responses.

Rationale: Inkscape extension crashes (e.g. AttributeError in inkex scripts) produce
nonzero exit codes with diagnostic content on stderr. Without surfacing stderr, callers
receive only "inkscape failed" with no debugging information.
See: docs/observer-log.md, P4 BLOCKER.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from inkscape_mcp.cli_server import (
    _execute_subprocess,
    _init_config,
    _action_run_impl,
    Doc,
)
from inkscape_mcp.config import InkscapeConfig


@pytest.fixture
def workspace(tmp_path):
    config = InkscapeConfig(
        workspace=tmp_path,
        max_file_size=1024 * 1024,
        timeout_default=30,
        max_concurrent=2,
    )
    _init_config(config)
    return tmp_path


class TestExecuteSubprocessSurfacesStderr:
    """_execute_subprocess must include stderr content in ToolError on nonzero exit."""

    def test_nonzero_exit_includes_stderr_in_message(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (
            b"",
            b"AttributeError: module 'inkex' has no attribute 'ColorError'",
        )
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ToolError) as exc_info:
                _execute_subprocess(["inkscape", "--batch-process"], 30, {})
        error_msg = str(exc_info.value)
        assert "ColorError" in error_msg or "inkex" in error_msg

    def test_nonzero_exit_with_empty_stderr_still_raises(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.communicate.return_value = (b"", b"")
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ToolError) as exc_info:
                _execute_subprocess(["inkscape"], 30, {})
        assert "inkscape failed" in str(exc_info.value)

    def test_stderr_truncated_to_500_chars_on_error(self):
        long_stderr = b"E: " + b"x" * 2000
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", long_stderr)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ToolError) as exc_info:
                _execute_subprocess(["inkscape"], 30, {})
        error_msg = str(exc_info.value)
        assert len(error_msg) < 600

    def test_zero_exit_returns_stdout_and_stderr(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"stdout data", b"warning: something")
        with patch("subprocess.Popen", return_value=mock_proc):
            stdout, stderr = _execute_subprocess(["inkscape"], 30, {})
        assert stdout == b"stdout data"
        assert stderr == b"warning: something"

    def test_nonzero_exit_with_multiline_stderr(self):
        stderr_content = b"Traceback (most recent call last):\n  File 'ext.py'\nAttributeError: 'NoneType'"
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", stderr_content)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ToolError) as exc_info:
                _execute_subprocess(["inkscape"], 30, {})
        assert "AttributeError" in str(exc_info.value)


class TestActionRunImplSurfacesWarnings:
    """_action_run_impl must include Inkscape warnings in success response."""

    @pytest.mark.asyncio
    async def test_success_with_warnings_includes_warnings_key(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.return_value = (b"", b"WARNING: unknown LPE parameter 'max_path_size'")
            result = await _action_run_impl(
                Doc(type="file", path="test.svg"),
                actions=["select-all"],
                export=None,
            )
        assert result["ok"] is True
        assert "warnings" in result
        assert "max_path_size" in result["warnings"]

    @pytest.mark.asyncio
    async def test_success_with_empty_stderr_has_no_warnings_key(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.return_value = (b"", b"")
            result = await _action_run_impl(
                Doc(type="file", path="test.svg"),
                actions=["select-all"],
                export=None,
            )
        assert result["ok"] is True
        assert "warnings" not in result

    @pytest.mark.asyncio
    async def test_success_with_whitespace_only_stderr_has_no_warnings_key(
        self, workspace, tmp_path
    ):
        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.return_value = (b"", b"   \n  \n  ")
            result = await _action_run_impl(
                Doc(type="file", path="test.svg"),
                actions=["select-all"],
                export=None,
            )
        assert result["ok"] is True
        assert "warnings" not in result

    @pytest.mark.asyncio
    async def test_warnings_truncated_to_1000_chars(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.return_value = (b"", b"W: " + b"y" * 5000)
            result = await _action_run_impl(
                Doc(type="file", path="test.svg"),
                actions=["select-all"],
                export=None,
            )
        assert "warnings" in result
        assert len(result["warnings"]) <= 1000

    @pytest.mark.asyncio
    async def test_failure_propagates_stderr_from_tool_error(self, workspace, tmp_path):
        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.side_effect = ToolError(
                "inkscape failed: AttributeError: module 'inkex' has no attribute 'ColorError'"
            )
            with pytest.raises(ToolError) as exc_info:
                await _action_run_impl(
                    Doc(type="file", path="test.svg"),
                    actions=["select-all"],
                    export=None,
                )
        assert "ColorError" in str(exc_info.value)


class TestMCPLayerSurfacesStderr:
    """End-to-end: stderr must propagate through the MCP client layer."""

    @pytest.mark.asyncio
    async def test_mcp_client_receives_stderr_in_error(self, workspace, tmp_path):
        from inkscape_mcp.cli_server import app

        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.side_effect = ToolError(
                "inkscape failed: Fatal Python error: no module named inkex"
            )
            async with Client(app) as client:
                with pytest.raises(Exception) as exc_info:
                    await client.call_tool(
                        "action_run",
                        {
                            "doc": {"type": "file", "path": "test.svg"},
                            "actions": ["select-all"],
                        },
                    )
        error_text = str(exc_info.value)
        assert "inkex" in error_text or "failed" in error_text

    @pytest.mark.asyncio
    async def test_mcp_success_response_includes_warnings(self, workspace, tmp_path):
        from inkscape_mcp.cli_server import app

        infile = tmp_path / "test.svg"
        infile.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')

        with patch("inkscape_mcp.cli_server._run_inkscape") as mock_run:
            mock_run.return_value = (b"", b"Inkscape warning: deprecated attribute")
            async with Client(app) as client:
                result = await client.call_tool(
                    "action_run",
                    {
                        "doc": {"type": "file", "path": "test.svg"},
                        "actions": ["select-all"],
                    },
                )
        assert result.data.get("ok") is True
        assert "warnings" in result.data
        assert "deprecated" in result.data["warnings"]
