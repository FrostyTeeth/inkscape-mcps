"""Tests for create_layer DOM tool — RED → GREEN → REFACTOR TDD."""

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestCreateLayer:
    """Tests for the create_layer tool on dom_server.app."""

    # ------------------------------------------------------------------
    # Happy-path tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_layer_appends_g_with_inkscape_groupmode(
        self, dom_test_config, base_svg
    ):
        """New layer must have inkscape:groupmode="layer" and the given label."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_layer",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "layer": {"name": "Background"},
                    "save_as": "layer_groupmode.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1

        out_path = dom_test_config.workspace / "layer_groupmode.svg"
        assert out_path.exists()
        content = out_path.read_text()
        assert 'inkscape:groupmode="layer"' in content
        assert 'inkscape:label="Background"' in content

    @pytest.mark.asyncio
    async def test_create_layer_auto_id_when_absent(
        self, dom_test_config, base_svg
    ):
        """When no id is provided, a valid auto-generated id must be returned."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_layer",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "layer": {"name": "Auto ID Layer"},
                    "save_as": "layer_auto_id.svg",
                },
            )

        assert "id" in result.data
        generated_id = result.data["id"]
        assert generated_id  # non-empty
        # Must be a valid XML id: starts with letter or underscore
        assert generated_id[0].isalpha() or generated_id[0] == "_"

    @pytest.mark.asyncio
    async def test_create_layer_explicit_id(self, dom_test_config, base_svg):
        """Providing an explicit id must use it verbatim in the output."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_layer",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "layer": {"name": "Named Layer", "id": "my-layer"},
                    "save_as": "layer_explicit_id.svg",
                },
            )

        assert result.data.get("id") == "my-layer"
        out_path = dom_test_config.workspace / "layer_explicit_id.svg"
        content = out_path.read_text()
        assert 'id="my-layer"' in content

    @pytest.mark.asyncio
    async def test_create_layer_nested_under_parent_id(
        self, dom_test_config, layered_svg
    ):
        """New layer must appear as a child of the element identified by parent_id."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "create_layer",
                {
                    "doc": {"type": "inline", "svg": layered_svg},
                    "layer": {
                        "name": "Sub Layer",
                        "id": "sub-layer",
                        "parent_id": "layer1",
                    },
                    "save_as": "layer_nested.svg",
                },
            )

        assert result.data.get("ok") is True
        out_path = dom_test_config.workspace / "layer_nested.svg"
        content = out_path.read_text()
        # The sub-layer element must exist in the output
        assert 'id="sub-layer"' in content
        assert 'inkscape:label="Sub Layer"' in content

        # Structural check: sub-layer must appear inside layer1's <g> block
        idx_layer1 = content.index('id="layer1"')
        idx_sub = content.index('id="sub-layer"')
        idx_layer2 = content.index('id="layer2"')
        # sub-layer should appear after layer1 and before layer2
        assert idx_layer1 < idx_sub < idx_layer2

    @pytest.mark.asyncio
    async def test_create_layer_ensures_inkscape_namespace_declared(
        self, dom_test_config, base_svg
    ):
        """The Inkscape namespace must be declared on the root after save."""
        async with Client(dom_server.app) as client:
            await client.call_tool(
                "create_layer",
                {
                    "doc": {"type": "inline", "svg": base_svg},
                    "layer": {"name": "NS Test Layer"},
                    "save_as": "layer_ns.svg",
                },
            )

        out_path = dom_test_config.workspace / "layer_ns.svg"
        content = out_path.read_text()
        assert "http://www.inkscape.org/namespaces/inkscape" in content

    # ------------------------------------------------------------------
    # Edge / error cases
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_layer_rejects_duplicate_id(
        self, dom_test_config, layered_svg
    ):
        """Supplying an id that already exists in the SVG must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": layered_svg},
                        "layer": {"name": "Dup", "id": "layer1"},
                        "save_as": "layer_dup_id.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_layer_rejects_unsafe_name_lt(
        self, dom_test_config, base_svg
    ):
        """Name containing '<' must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "layer": {"name": "<evil>"},
                        "save_as": "layer_unsafe_name.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_layer_rejects_unsafe_name_quote(
        self, dom_test_config, base_svg
    ):
        """Name containing '"' must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "layer": {"name": 'say "hello"'},
                        "save_as": "layer_unsafe_quote.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_layer_rejects_unsafe_id_numeric_start(
        self, dom_test_config, base_svg
    ):
        """id starting with a digit must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "layer": {"name": "Bad ID Layer", "id": "1bad"},
                        "save_as": "layer_bad_id.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_layer_rejects_unsafe_id_script_tag(
        self, dom_test_config, base_svg
    ):
        """id resembling a script tag must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "layer": {"name": "Script ID", "id": "<script>"},
                        "save_as": "layer_script_id.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_create_layer_parent_not_found_raises(
        self, dom_test_config, base_svg
    ):
        """Specifying a parent_id that does not exist must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "create_layer",
                    {
                        "doc": {"type": "inline", "svg": base_svg},
                        "layer": {
                            "name": "Orphan Layer",
                            "parent_id": "nonexistent-parent",
                        },
                        "save_as": "layer_bad_parent.svg",
                    },
                )


class TestRenameLayer:
    """Tests for the rename_layer tool on dom_server.app."""

    @pytest.mark.asyncio
    async def test_rename_layer_updates_inkscape_label(
        self, dom_test_config, layered_svg
    ):
        """After rename, the target layer's inkscape:label must equal the new name."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "rename_layer",
                {
                    "doc": {"type": "inline", "svg": layered_svg},
                    "layer_id": "layer1",
                    "new_name": "Renamed Layer",
                    "save_as": "rename_label.svg",
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("changed") == 1

        out_path = dom_test_config.workspace / "rename_label.svg"
        assert out_path.exists()
        content = out_path.read_text()
        assert 'inkscape:label="Renamed Layer"' in content

    @pytest.mark.asyncio
    async def test_rename_layer_leaves_other_layers_alone(
        self, dom_test_config, layered_svg
    ):
        """Renaming layer1 must not change layer2's label."""
        async with Client(dom_server.app) as client:
            await client.call_tool(
                "rename_layer",
                {
                    "doc": {"type": "inline", "svg": layered_svg},
                    "layer_id": "layer1",
                    "new_name": "Only This One",
                    "save_as": "rename_other_untouched.svg",
                },
            )

        out_path = dom_test_config.workspace / "rename_other_untouched.svg"
        content = out_path.read_text()
        # layer2 retains its original label
        assert 'inkscape:label="Layer 2"' in content

    @pytest.mark.asyncio
    async def test_rename_layer_preserves_id(
        self, dom_test_config, layered_svg
    ):
        """The layer's id attribute must be unchanged after renaming."""
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "rename_layer",
                {
                    "doc": {"type": "inline", "svg": layered_svg},
                    "layer_id": "layer1",
                    "new_name": "New Name",
                    "save_as": "rename_preserves_id.svg",
                },
            )

        assert result.data.get("id") == "layer1"
        out_path = dom_test_config.workspace / "rename_preserves_id.svg"
        content = out_path.read_text()
        assert 'id="layer1"' in content

    @pytest.mark.asyncio
    async def test_rename_layer_not_found_raises(
        self, dom_test_config, layered_svg
    ):
        """Supplying an id that does not exist must raise an error."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "rename_layer",
                    {
                        "doc": {"type": "inline", "svg": layered_svg},
                        "layer_id": "nonexistent",
                        "new_name": "Whatever",
                        "save_as": "rename_not_found.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_rename_layer_rejects_non_layer_group(
        self, dom_test_config, shape_svg
    ):
        """A <g> WITHOUT inkscape:groupmode="layer" must be rejected."""
        # shape_svg has rect/circle/text — none are Inkscape layers
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "rename_layer",
                    {
                        "doc": {"type": "inline", "svg": shape_svg},
                        "layer_id": "rect1",
                        "new_name": "Not A Layer",
                        "save_as": "rename_non_layer.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_rename_layer_rejects_unsafe_name(
        self, dom_test_config, layered_svg
    ):
        """new_name containing '<', '>', or '"' must be rejected."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "rename_layer",
                    {
                        "doc": {"type": "inline", "svg": layered_svg},
                        "layer_id": "layer1",
                        "new_name": '<script>alert("xss")</script>',
                        "save_as": "rename_unsafe_name.svg",
                    },
                )

    @pytest.mark.asyncio
    async def test_rename_layer_rejects_unsafe_id(
        self, dom_test_config, layered_svg
    ):
        """layer_id not matching _validate_id pattern must raise ValidationError."""
        with pytest.raises(Exception):
            async with Client(dom_server.app) as client:
                await client.call_tool(
                    "rename_layer",
                    {
                        "doc": {"type": "inline", "svg": layered_svg},
                        "layer_id": "1invalid-start",
                        "new_name": "Anything",
                        "save_as": "rename_unsafe_id.svg",
                    },
                )
