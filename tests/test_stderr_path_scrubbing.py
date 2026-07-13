"""TDD RED phase: stderr surfaced to MCP clients must not leak host filesystem paths.

Regression test for a code-review finding: _execute_subprocess's ToolError
message and _action_run_impl's "warnings" field return raw Inkscape/GLib
stderr verbatim, which commonly includes absolute paths (workspace temp
files, $HOME, font/theme paths). Stderr surfacing itself is intentional
(see tests/test_stderr_surfacing.py, docs/observer-log.md P4 BLOCKER) —
this test only requires that absolute filesystem paths within it are
redacted before being returned to a client, while other diagnostic
content (exception names/messages) is preserved.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from inkscape_mcp.cli_server import _execute_subprocess, _scrub_paths


class TestScrubPaths:
    def test_redacts_unix_absolute_path(self):
        text = 'File "/Users/sgminim1/project/workspace/inline-abc123.svg", line 3'
        scrubbed = _scrub_paths(text)
        assert "/Users/sgminim1" not in scrubbed
        assert "inline-abc123.svg" not in scrubbed

    def test_preserves_non_path_diagnostic_content(self):
        text = 'AttributeError: module \'inkex\' has no attribute \'ColorError\''
        scrubbed = _scrub_paths(text)
        assert scrubbed == text

    def test_redacts_path_but_keeps_surrounding_message(self):
        text = "Traceback (most recent call last):\n  File \"/Users/sgminim1/x/ext.py\", line 3\nAttributeError: 'NoneType'"
        scrubbed = _scrub_paths(text)
        assert "AttributeError: 'NoneType'" in scrubbed
        assert "Traceback (most recent call last):" in scrubbed
        assert "/Users/sgminim1" not in scrubbed


class TestExecuteSubprocessScrubsPathsFromErrorMessage:
    def test_error_message_has_paths_redacted(self):
        stderr = b'File "/Users/sgminim1/secret-project/workspace/inline-xyz.svg": ColorError'
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", stderr)
        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ToolError) as exc_info:
                _execute_subprocess(["inkscape"], 30, {})
        error_msg = str(exc_info.value)
        assert "/Users/sgminim1/secret-project" not in error_msg
        assert "ColorError" in error_msg
