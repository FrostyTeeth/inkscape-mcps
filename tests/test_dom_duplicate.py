"""Tests for duplicate_object DOM tool — RED → GREEN → REFACTOR TDD."""

import re

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestDuplicateObject:
    """Tests for the duplicate_object tool on dom_server.app."""

    # ------------------------------------------------------------------
    # Happy-path tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_duplicate_object_by_id(self, dom_test_config, shape_svg):
        """Input has <rect id="rect1">; after duplicate, output contains 2 rects
        and result.data['changed'] == 1."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#rect1"},
                    "doc": {"type": "inline", "svg": shape_svg},
                    "save_as": "dup_by_id.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1

        out_path = dom_test_config.workspace / "dup_by_id.svg"
        assert out_path.exists()
        content = out_path.read_text()
        # Two rects must be present
        assert content.count("<rect") == 2

    @pytest.mark.asyncio
    async def test_duplicate_object_auto_id_when_absent(
        self, dom_test_config, shape_svg
    ):
        """When new_id is not supplied, the copy gets an auto-generated id
        matching the _validate_id regex (starts with letter/underscore)."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#rect1"},
                    "doc": {"type": "inline", "svg": shape_svg},
                    "save_as": "dup_auto_id.svg",
                },
            )

        assert result.data.get("ok") is True
        returned_id = result.data.get("id")
        assert returned_id is not None
        # Must satisfy _ID_RE: starts with letter/underscore, up to 64 chars
        assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$", returned_id), (
            f"Auto-generated id {returned_id!r} doesn't match _ID_RE"
        )

    @pytest.mark.asyncio
    async def test_duplicate_object_explicit_new_id(self, dom_test_config, shape_svg):
        """When new_id='copy1' is supplied, the copy has id='copy1'."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#rect1"},
                    "new_id": "copy1",
                    "doc": {"type": "inline", "svg": shape_svg},
                    "save_as": "dup_explicit_id.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("id") == "copy1"

        out_path = dom_test_config.workspace / "dup_explicit_id.svg"
        content = out_path.read_text()
        assert 'id="copy1"' in content

    @pytest.mark.asyncio
    async def test_duplicate_object_applies_transform_offset(
        self, dom_test_config, shape_svg
    ):
        """offset_dx=10, offset_dy=5 → copy has translate(10,5) in its transform."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#rect1"},
                    "new_id": "rect1-offset",
                    "offset_dx": 10.0,
                    "offset_dy": 5.0,
                    "doc": {"type": "inline", "svg": shape_svg},
                    "save_as": "dup_transform.svg",
                },
            )

        assert result.data.get("ok") is True

        out_path = dom_test_config.workspace / "dup_transform.svg"
        content = out_path.read_text()
        # The copy should contain a translate(10,...5...) transform
        assert "translate(10" in content
        assert "rect1-offset" in content

    @pytest.mark.asyncio
    async def test_duplicate_object_preserves_children(
        self, dom_test_config, layered_svg
    ):
        """Duplicating a <g> with nested elements produces a deep copy including children."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#layer1"},
                    "new_id": "layer1-copy",
                    "doc": {"type": "inline", "svg": layered_svg},
                    "save_as": "dup_children.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1

        out_path = dom_test_config.workspace / "dup_children.svg"
        content = out_path.read_text()
        # Both the original layer and the copy should be present
        assert 'id="layer1"' in content
        assert 'id="layer1-copy"' in content
        # The child rect from layer1 should appear twice (original + copy)
        assert content.count("<rect") == 2

    @pytest.mark.asyncio
    async def test_duplicate_object_not_found_returns_changed_zero(
        self, dom_test_config, shape_svg
    ):
        """Selector matches nothing → {ok: True, changed: 0, out: None, id: None}."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#nonexistent"},
                    "doc": {"type": "inline", "svg": shape_svg},
                    "save_as": "dup_not_found.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 0
        assert result.data.get("out") is None
        assert result.data.get("id") is None

    # ------------------------------------------------------------------
    # Validation / error tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_duplicate_object_rejects_unsafe_new_id(
        self, dom_test_config, shape_svg
    ):
        """new_id='1bad' (starts with digit) must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "duplicate_object",
                    {
                        "source": {"type": "css", "value": "#rect1"},
                        "new_id": "1bad",
                        "doc": {"type": "inline", "svg": shape_svg},
                        "save_as": "dup_bad_id.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_duplicate_object_dangerous_subtree_sanitized(
        self, dom_test_config
    ):
        """Source containing a <script> child — after duplicate + save,
        neither the original nor the copy retains the script element."""
        evil_svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <g id="evil-group">\n'
            '    <rect x="0" y="0" width="50" height="50"/>\n'
            '    <script>alert(1)</script>\n'
            "  </g>\n"
            "</svg>"
        )

        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "duplicate_object",
                {
                    "source": {"type": "css", "value": "#evil-group"},
                    "new_id": "evil-group-copy",
                    "doc": {"type": "inline", "svg": evil_svg},
                    "save_as": "dup_sanitized.svg",
                },
            )

        assert result.data.get("ok") is True

        out_path = dom_test_config.workspace / "dup_sanitized.svg"
        content = out_path.read_text()
        # No <script> should appear anywhere in the output
        assert "<script" not in content.lower()
