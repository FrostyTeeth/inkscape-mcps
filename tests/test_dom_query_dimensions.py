"""Tests for query_dimensions DOM tool — RED → GREEN → REFACTOR TDD."""

import os
from pathlib import Path

import pytest
from fastmcp import Client

import inkscape_mcp.dom_server as dom_server


class TestQueryDimensions:
    """Tests for the query_dimensions tool on dom_server.app."""

    # ------------------------------------------------------------------
    # Happy-path: per-shape-type tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_query_dimensions_rect(self, dom_test_config):
        """<rect x="5" y="10" width="20" height="30"> → bbox=(5,10,25,40)."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="5" y="10" width="20" height="30"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#r1"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 1
        m = matches[0]
        assert m["id"] == "r1"
        assert m["tag"] == "rect"
        assert m["x"] == 5.0
        assert m["y"] == 10.0
        assert m["width"] == 20.0
        assert m["height"] == 30.0
        assert m["bbox"] == {"x1": 5.0, "y1": 10.0, "x2": 25.0, "y2": 40.0}

    @pytest.mark.asyncio
    async def test_query_dimensions_circle(self, dom_test_config):
        """cx=50, cy=50, r=10 → x=40, y=40, width=20, height=20, bbox=(40,40,60,60)."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <circle id="c1" cx="50" cy="50" r="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#c1"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 1
        m = matches[0]
        assert m["id"] == "c1"
        assert m["tag"] == "circle"
        assert m["x"] == 40.0
        assert m["y"] == 40.0
        assert m["width"] == 20.0
        assert m["height"] == 20.0
        assert m["bbox"] == {"x1": 40.0, "y1": 40.0, "x2": 60.0, "y2": 60.0}

    @pytest.mark.asyncio
    async def test_query_dimensions_ellipse(self, dom_test_config):
        """cx=50, cy=50, rx=20, ry=10 → x=30, y=40, width=40, height=20."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <ellipse id="e1" cx="50" cy="50" rx="20" ry="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#e1"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 1
        m = matches[0]
        assert m["id"] == "e1"
        assert m["tag"] == "ellipse"
        assert m["x"] == 30.0
        assert m["y"] == 40.0
        assert m["width"] == 40.0
        assert m["height"] == 20.0
        assert m["bbox"] == {"x1": 30.0, "y1": 40.0, "x2": 70.0, "y2": 60.0}

    @pytest.mark.asyncio
    async def test_query_dimensions_line(self, dom_test_config):
        """x1=10, y1=30, x2=80, y2=5 → bbox=(10,5,80,30), width=70, height=25."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <line id="l1" x1="10" y1="30" x2="80" y2="5"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#l1"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 1
        m = matches[0]
        assert m["id"] == "l1"
        assert m["tag"] == "line"
        assert m["x"] == 10.0
        assert m["y"] == 5.0
        assert m["width"] == 70.0
        assert m["height"] == 25.0
        assert m["bbox"] == {"x1": 10.0, "y1": 5.0, "x2": 80.0, "y2": 30.0}

    @pytest.mark.asyncio
    async def test_query_dimensions_multiple_matches_returns_list(self, dom_test_config):
        """Selector matches 2 elements → matches list length == 2, in document order."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" class="box" x="0" y="0" width="10" height="10"/>\n'
            '  <rect id="r2" class="box" x="20" y="20" width="30" height="30"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "rect"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 2
        # Document order: r1 first, r2 second
        assert matches[0]["id"] == "r1"
        assert matches[1]["id"] == "r2"

    @pytest.mark.asyncio
    async def test_query_dimensions_no_match_returns_empty_list(self, dom_test_config):
        """Unknown selector → {"ok": True, "matches": []}."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="0" y="0" width="10" height="10"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#nonexistent"},
                },
            )

        assert result.data.get("ok") is True
        assert result.data.get("matches") == []

    @pytest.mark.asyncio
    async def test_query_dimensions_unsupported_element_returns_none_dims(
        self, dom_test_config
    ):
        """<text> element → {id, tag, x: None, y: None, width: None, height: None, bbox: None}."""
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <text id="t1" x="50" y="180">Hello</text>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#t1"},
                },
            )

        assert result.data.get("ok") is True
        matches = result.data.get("matches")
        assert len(matches) == 1
        m = matches[0]
        assert m["id"] == "t1"
        assert m["tag"] == "text"
        assert m["x"] is None
        assert m["y"] is None
        assert m["width"] is None
        assert m["height"] is None
        assert m["bbox"] is None

    @pytest.mark.asyncio
    async def test_query_dimensions_does_not_write_any_file(self, dom_test_config):
        """query_dimensions is read-only — no files should be written to the workspace."""
        workspace: Path = dom_test_config.workspace
        # Snapshot files before the call
        files_before = set(workspace.iterdir())

        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
            '  <rect id="r1" x="1" y="2" width="3" height="4"/>\n'
            "</svg>"
        )
        async with Client(dom_server.app) as client:
            result = await client.call_tool(
                "query_dimensions",
                {
                    "doc": {"type": "inline", "svg": svg},
                    "selector": {"type": "css", "value": "#r1"},
                },
            )

        assert result.data.get("ok") is True
        files_after = set(workspace.iterdir())
        assert files_after == files_before, (
            f"query_dimensions wrote unexpected files: {files_after - files_before}"
        )
