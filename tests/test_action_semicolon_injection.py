"""TDD RED phase: action allowlist must reject ';'-smuggled Inkscape actions.

Regression test for a code-review finding: _is_safe_action() only checked
the token before the first ':', so an actions list element like
"select-by-id:x;file-close;export-do" passed validation (the prefix
"select-by-id" is allowlisted) but expanded, after ';'.join(acts) in
_mk_cmd, into multiple unvalidated Inkscape actions.
"""

import pytest
from pydantic import ValidationError

from inkscape_mcp.cli_server import RunArgs, _is_safe_action


class TestIsSafeActionRejectsSemicolons:
    def test_plain_safe_action_is_safe(self):
        assert _is_safe_action("select-all") is True

    def test_safe_action_with_arg_is_safe(self):
        assert _is_safe_action("select-by-id:x") is True

    def test_semicolon_smuggled_action_is_unsafe(self):
        assert _is_safe_action("select-by-id:x;file-close;export-do") is False

    def test_semicolon_smuggled_unsafe_action_is_unsafe(self):
        assert _is_safe_action("select-all;shell-command:rm -rf /") is False


class TestRunArgsRejectsSemicolonSmuggledActions:
    def test_actions_with_semicolon_raise(self):
        with pytest.raises(ValidationError, match="Unsafe action"):
            RunArgs(
                doc={"type": "inline", "svg": "<svg/>"},
                actions=["select-by-id:x;file-close;export-do"],
            )

    def test_plain_safe_actions_still_accepted(self):
        args = RunArgs(
            doc={"type": "inline", "svg": "<svg/>"},
            actions=["select-all", "path-union"],
        )
        assert args.actions == ["select-all", "path-union"]
