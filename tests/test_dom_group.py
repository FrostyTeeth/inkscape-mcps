"""Tests for group_objects DOM tool — RED → GREEN → REFACTOR TDD."""

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestGroupObjects:
    """Tests for the group_objects tool on dom_server.app."""

    # ------------------------------------------------------------------
    # Happy-path tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_group_objects_wraps_matches_in_new_g(self, dom_test_config):
        """Matched elements are wrapped in a new <g> inserted at the position
        of the first match; result.data['changed'] == number of matched elements."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            '  <circle id="c1" cx="50" cy="50" r="10"/>\n'
            '  <rect id="r2" x="20" y="20" width="10" height="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "group_objects",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selectors": [{"type": "css", "value": "rect"}],
                    "save_as": "group_basic.svg",
                    "group_id": "grp-rects",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 2

        out_path = dom_test_config.workspace / "group_basic.svg"
        content = out_path.read_text()
        # A <g id="grp-rects"> must be present
        assert 'id="grp-rects"' in content
        # Both rects must be children of the group — they appear after the <g> open tag
        # The circle should still exist outside the group
        assert content.count("<rect") == 2
        assert content.count("<circle") == 1

    @pytest.mark.asyncio
    async def test_group_objects_auto_id(self, dom_test_config):
        """When group_id is not supplied, an auto-generated id is assigned and
        returned in result.data['id']."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "group_objects",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selectors": [{"type": "css", "value": "#r1"}],
                    "save_as": "group_auto_id.svg",
                },
            )

        assert result.data.get("ok") is True
        gid = result.data.get("id")
        assert gid is not None
        assert gid.startswith("group-")

        out_path = dom_test_config.workspace / "group_auto_id.svg"
        content = out_path.read_text()
        assert f'id="{gid}"' in content

    @pytest.mark.asyncio
    async def test_group_objects_explicit_id(self, dom_test_config):
        """group_id='grp1' → the new <g> element has id='grp1'."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "group_objects",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selectors": [{"type": "css", "value": "#r1"}],
                    "save_as": "group_explicit.svg",
                    "group_id": "grp1",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("id") == "grp1"

        out_path = dom_test_config.workspace / "group_explicit.svg"
        content = out_path.read_text()
        assert 'id="grp1"' in content

    @pytest.mark.asyncio
    async def test_group_objects_preserves_sibling_order_outside_group(
        self, dom_test_config
    ):
        """Elements NOT matched remain in their original positions relative to the
        new <g>.  The <g> appears where the first match was."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <circle id="c0" cx="5" cy="5" r="5"/>\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            '  <circle id="c1" cx="50" cy="50" r="10"/>\n'
            '  <rect id="r2" x="20" y="20" width="10" height="10"/>\n'
            '  <circle id="c2" cx="90" cy="90" r="5"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "group_objects",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selectors": [{"type": "css", "value": "rect"}],
                    "save_as": "group_siblings.svg",
                    "group_id": "rect-group",
                },
            )

        assert result.data.get("ok") is True

        out_path = dom_test_config.workspace / "group_siblings.svg"
        content = out_path.read_text()

        # All three circles and two rects must still be present
        assert content.count("<circle") == 3
        assert content.count("<rect") == 2

        # c0 must appear before the group (it was before r1)
        pos_c0 = content.index('id="c0"')
        pos_group = content.index('id="rect-group"')
        assert pos_c0 < pos_group, "c0 should appear before the group"

        # c2 must appear after the group (it was after r2)
        pos_c2 = content.index('id="c2"')
        assert pos_c2 > pos_group, "c2 should appear after the group"

    @pytest.mark.asyncio
    async def test_group_objects_no_match_returns_changed_zero_and_no_write(
        self, dom_test_config
    ):
        """When selector matches nothing, return {ok: True, changed: 0, out: None}
        and do NOT write any file."""
        workspace = dom_test_config.workspace
        files_before = set(workspace.iterdir())

        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "group_objects",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selectors": [{"type": "css", "value": "#nonexistent"}],
                    "save_as": "group_no_match.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 0
        assert result.data.get("out") is None

        files_after = set(workspace.iterdir())
        assert files_after == files_before, (
            f"group_objects wrote unexpected files: {files_after - files_before}"
        )

    # ------------------------------------------------------------------
    # Validation / error tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_group_objects_rejects_duplicate_id(self, dom_test_config):
        """If group_id already exists in the SVG, raise ValidationError."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="existing" x="0" y="0" width="10" height="10"/>\n'
            '  <circle id="c1" cx="50" cy="50" r="10"/>\n'
            "</svg>"
        )
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "group_objects",
                    {
                        "doc": {"type": "inline", "svg": svg},
                        "selectors": [{"type": "css", "value": "circle"}],
                        "save_as": "group_dup_id.svg",
                        "group_id": "existing",
                    },
                )

    @pytest.mark.asyncio
    async def test_group_objects_rejects_unsafe_id(self, dom_test_config):
        """group_id='1bad' (starts with digit) must be rejected before any file write."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "group_objects",
                    {
                        "doc": {"type": "inline", "svg": svg},
                        "selectors": [{"type": "css", "value": "#r1"}],
                        "save_as": "group_bad_id.svg",
                        "group_id": "1bad",
                    },
                )

    @pytest.mark.asyncio
    async def test_group_objects_respects_selector_limit(self, dom_test_config):
        """Passing 33 selectors must raise a ValidationError (max is 32)."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        selectors = [{"type": "css", "value": "rect"}] * 33
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "group_objects",
                    {
                        "doc": {"type": "inline", "svg": svg},
                        "selectors": selectors,
                        "save_as": "group_too_many.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_group_objects_rejects_grouping_root(self, dom_test_config):
        """A selector that matches the root <svg> element itself must raise ValidationError."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg id="root-svg" xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "group_objects",
                    {
                        "doc": {"type": "inline", "svg": svg},
                        "selectors": [{"type": "css", "value": "#root-svg"}],
                        "save_as": "group_root.svg",
                    },
                )
