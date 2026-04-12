"""Tests for create_gradient DOM tool — RED → GREEN → REFACTOR TDD."""

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestCreateGradient:
    """Tests for the create_gradient tool on dom_server.app."""

    # ------------------------------------------------------------------
    # Happy-path tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_linear_gradient_adds_to_defs(
        self, dom_test_config, base_svg
    ):
        """New linear gradient must appear inside <defs> with 2 stop children."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "linear",
                        "stops": [
                            {"offset": 0.0, "color": "#ff0000"},
                            {"offset": 1.0, "color": "#00ff00"},
                        ],
                    },
                    "save_as": "gradient_linear_basic.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1

        out_path = dom_test_config.workspace / "gradient_linear_basic.svg"
        assert out_path.exists()
        content = out_path.read_text()
        assert "<linearGradient" in content
        assert "<defs" in content
        # Both stops should be present
        assert content.count("<stop") == 2

    @pytest.mark.asyncio
    async def test_create_radial_gradient_adds_to_defs(
        self, dom_test_config, base_svg
    ):
        """New radial gradient must appear with <radialGradient> tag."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "radial",
                        "stops": [
                            {"offset": 0.0, "color": "#ffffff"},
                            {"offset": 1.0, "color": "#000000"},
                        ],
                    },
                    "save_as": "gradient_radial_basic.svg",
                },
            )

        assert result.data.get("ok") is True

        out_path = dom_test_config.workspace / "gradient_radial_basic.svg"
        content = out_path.read_text()
        assert "<radialGradient" in content
        assert "<defs" in content

    @pytest.mark.asyncio
    async def test_create_gradient_creates_defs_if_missing(
        self, dom_test_config, base_svg
    ):
        """Input SVG without <defs> must have <defs> created with gradient inside."""
        # base_svg has no <defs>
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "linear",
                        "stops": [
                            {"offset": 0.0, "color": "#aabbcc"},
                            {"offset": 1.0, "color": "#112233"},
                        ],
                    },
                    "save_as": "gradient_creates_defs.svg",
                },
            )

        assert result.data.get("ok") is True

        out_path = dom_test_config.workspace / "gradient_creates_defs.svg"
        content = out_path.read_text()
        assert "<defs" in content
        assert "<linearGradient" in content
        # gradient must appear after defs opening
        assert content.index("<defs") < content.index("<linearGradient")

    @pytest.mark.asyncio
    async def test_create_gradient_returns_id_for_reuse(
        self, dom_test_config, base_svg
    ):
        """result.data['id'] must equal the gradient's id attribute in the output."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "linear",
                        "id": "my-grad",
                        "stops": [
                            {"offset": 0.0, "color": "#ff0000"},
                            {"offset": 1.0, "color": "#0000ff"},
                        ],
                    },
                    "save_as": "gradient_returns_id.svg",
                },
            )

        assert result.data.get("id") == "my-grad"

        out_path = dom_test_config.workspace / "gradient_returns_id.svg"
        content = out_path.read_text()
        assert 'id="my-grad"' in content

    @pytest.mark.asyncio
    async def test_create_gradient_linear_uses_default_coords_when_none(
        self, dom_test_config, base_svg
    ):
        """When no x1/y1/x2/y2 are provided, no coord attrs on the gradient element."""
        async with Client(dom_server.app) as client:
            await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "linear",
                        "id": "grad-no-coords",
                        "stops": [
                            {"offset": 0.0, "color": "#aaaaaa"},
                            {"offset": 1.0, "color": "#555555"},
                        ],
                    },
                    "save_as": "gradient_no_coords.svg",
                },
            )

        out_path = dom_test_config.workspace / "gradient_no_coords.svg"
        content = out_path.read_text()
        # Extract just the linearGradient tag portion (everything between < and >)
        import re
        match = re.search(r"<linearGradient[^>]*>", content)
        assert match is not None
        tag_str = match.group(0)
        # No coordinate attributes should be present
        assert "x1=" not in tag_str
        assert "y1=" not in tag_str
        assert "x2=" not in tag_str
        assert "y2=" not in tag_str

    @pytest.mark.asyncio
    async def test_create_gradient_with_explicit_linear_coords(
        self, dom_test_config, base_svg
    ):
        """Providing x1/y1/x2/y2 must set those attrs on the gradient element."""
        async with Client(dom_server.app) as client:
            await client.call_tool(
                "create_gradient",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "gradient": {
                        "kind": "linear",
                        "id": "grad-with-coords",
                        "stops": [
                            {"offset": 0.0, "color": "#ff0000"},
                            {"offset": 1.0, "color": "#0000ff"},
                        ],
                        "x1": 0.1,
                        "y1": 0.0,
                        "x2": 1.0,
                        "y2": 0.0,
                    },
                    "save_as": "gradient_with_coords.svg",
                },
            )

        out_path = dom_test_config.workspace / "gradient_with_coords.svg"
        content = out_path.read_text()
        assert "x1=" in content
        assert "y1=" in content
        assert "x2=" in content
        assert "y2=" in content

    # ------------------------------------------------------------------
    # Validation / error tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_gradient_stop_colors_are_hex_only(
        self, dom_test_config, base_svg
    ):
        """Named colors (e.g. 'red') must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": [
                                {"offset": 0.0, "color": "red"},
                                {"offset": 1.0, "color": "#00ff00"},
                            ],
                        },
                        "save_as": "gradient_named_color.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_stop_colors_reject_rgb_function(
        self, dom_test_config, base_svg
    ):
        """rgb() function colors must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": [
                                {"offset": 0.0, "color": "rgb(1,2,3)"},
                                {"offset": 1.0, "color": "#00ff00"},
                            ],
                        },
                        "save_as": "gradient_rgb_func.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_rejects_too_few_stops(
        self, dom_test_config, base_svg
    ):
        """1 stop must be rejected (minimum is 2)."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": [
                                {"offset": 0.0, "color": "#ff0000"},
                            ],
                        },
                        "save_as": "gradient_too_few.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_rejects_too_many_stops(
        self, dom_test_config, base_svg
    ):
        """17 stops must be rejected (maximum is 16)."""
        stops = [{"offset": i / 16, "color": "#aabbcc"} for i in range(17)]
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": stops,
                        },
                        "save_as": "gradient_too_many.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_rejects_offset_out_of_range_high(
        self, dom_test_config, base_svg
    ):
        """offset=1.5 must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": [
                                {"offset": 0.0, "color": "#ff0000"},
                                {"offset": 1.5, "color": "#0000ff"},
                            ],
                        },
                        "save_as": "gradient_bad_offset_high.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_rejects_offset_out_of_range_low(
        self, dom_test_config, base_svg
    ):
        """offset=-0.1 must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "stops": [
                                {"offset": -0.1, "color": "#ff0000"},
                                {"offset": 1.0, "color": "#0000ff"},
                            ],
                        },
                        "save_as": "gradient_bad_offset_low.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_gradient_rejects_unsafe_id(
        self, dom_test_config, base_svg
    ):
        """id='1bad' (starts with digit) must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_gradient",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "gradient": {
                            "kind": "linear",
                            "id": "1bad",
                            "stops": [
                                {"offset": 0.0, "color": "#ff0000"},
                                {"offset": 1.0, "color": "#0000ff"},
                            ],
                        },
                        "save_as": "gradient_bad_id.svg",
                    },
                )
