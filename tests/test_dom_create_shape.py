"""Tests for create_shape DOM tool — RED phase."""

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestCreateShape:
    """Tests for the create_shape tool on dom_server.app."""

    @pytest.mark.asyncio
    async def test_create_rect_appends_to_root(self, dom_test_config, base_svg):
        """Basic rect creation — check XML output and result."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "rect",
                        "attrs": {"x": 10, "y": 10, "width": 50, "height": 30},
                        "style": {"fill": "#ff0000"},
                    },
                    "save_as": "create_rect_out.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1
        assert "id" in result.data

        out_path = dom_test_config.workspace / "create_rect_out.svg"
        assert out_path.exists()
        content = out_path.read_text()
        assert "<rect" in content
        assert "fill" in content

    @pytest.mark.asyncio
    async def test_create_circle_appended(self, dom_test_config, base_svg):
        """Circle creation — element appears in output file."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "circle",
                        "attrs": {"cx": 50, "cy": 50, "r": 20},
                    },
                    "save_as": "create_circle_out.svg",
                },
            )

        assert result.data.get("ok") is True
        out_path = dom_test_config.workspace / "create_circle_out.svg"
        content = out_path.read_text()
        assert "<circle" in content

    @pytest.mark.asyncio
    async def test_create_ellipse_appended(self, dom_test_config, base_svg):
        """Ellipse creation — element appears in output file."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "ellipse",
                        "attrs": {"cx": 50, "cy": 50, "rx": 30, "ry": 20},
                    },
                    "save_as": "create_ellipse_out.svg",
                },
            )

        assert result.data.get("ok") is True
        out_path = dom_test_config.workspace / "create_ellipse_out.svg"
        content = out_path.read_text()
        assert "ellipse" in content

    @pytest.mark.asyncio
    async def test_create_shape_rejects_unknown_kind(self, dom_test_config, base_svg):
        """Unknown shape kind must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_shape",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "shape": {
                            "kind": "spiral",
                            "attrs": {},
                        },
                        "save_as": "bad_kind.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_shape_rejects_unknown_attr(self, dom_test_config, base_svg):
        """Event-handler or unknown attribute must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_shape",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "shape": {
                            "kind": "rect",
                            "attrs": {
                                "onmouseover": "alert(1)",
                                "x": 10,
                                "width": 50,
                                "height": 30,
                            },
                        },
                        "save_as": "bad_attr.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_shape_rejects_unknown_style_prop(
        self, dom_test_config, base_svg
    ):
        """Unknown or dangerous style property must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_shape",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "shape": {
                            "kind": "rect",
                            "attrs": {"x": 10, "width": 50, "height": 30},
                            "style": {"behavior": "url(evil)"},
                        },
                        "save_as": "bad_style.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_shape_rejects_path_outside_workspace(
        self, dom_test_config, base_svg
    ):
        """Save path outside workspace must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_shape",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "shape": {
                            "kind": "rect",
                            "attrs": {"x": 10, "width": 50, "height": 30},
                        },
                        "save_as": "/etc/evil.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_shape_result_contains_id(self, dom_test_config, base_svg):
        """Result dict must include a non-empty 'id' field."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "rect",
                        "attrs": {"x": 0, "y": 0, "width": 20, "height": 10},
                    },
                    "save_as": "id_check.svg",
                },
            )

        assert "id" in result.data
        assert result.data["id"]  # non-empty string

    @pytest.mark.asyncio
    async def test_create_shape_custom_id(self, dom_test_config, base_svg):
        """Providing a custom id in shape spec must use it in the output."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "rect",
                        "attrs": {"x": 0, "y": 0, "width": 20, "height": 10},
                        "id": "my-rect-1",
                    },
                    "save_as": "custom_id.svg",
                },
            )

        assert result.data["id"] == "my-rect-1"
        out_path = dom_test_config.workspace / "custom_id.svg"
        content = out_path.read_text()
        assert 'id="my-rect-1"' in content

    @pytest.mark.asyncio
    async def test_create_shape_out_path_in_result(self, dom_test_config, base_svg):
        """Result must contain an absolute output path."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_shape",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "shape": {
                        "kind": "circle",
                        "attrs": {"cx": 50, "cy": 50, "r": 10},
                    },
                    "save_as": "path_check.svg",
                },
            )

        out = result.data.get("out", "")
        assert out.endswith("path_check.svg")
        assert out.startswith("/")  # absolute path
