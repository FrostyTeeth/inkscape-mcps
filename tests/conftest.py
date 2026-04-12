"""Shared test fixtures for inkscape-mcp tests."""

import tempfile
from pathlib import Path

import pytest

from inkscape_mcp.config import InkscapeConfig
from inkscape_mcp import dom_server, combined


@pytest.fixture(scope="session")
def temp_workspace():
    """Session-scoped temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def dom_test_config(temp_workspace):
    """InkscapeConfig wired into dom_server._init_config."""
    config = InkscapeConfig(
        workspace=temp_workspace, max_file_size=1024 * 1024, max_concurrent=2
    )
    dom_server._init_config(config)
    return config


@pytest.fixture
def combined_test_config(temp_workspace):
    """InkscapeConfig wired into combined._init_config."""
    config = InkscapeConfig(
        workspace=temp_workspace,
        max_file_size=2048,
        timeout_default=10,
        max_concurrent=2,
    )
    combined._init_config(config)
    return config


@pytest.fixture
def base_svg():
    """Minimal valid SVG string."""
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>'


@pytest.fixture
def layered_svg():
    """SVG with two Inkscape layers."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg"'
        ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
        ' width="200" height="200">\n'
        '  <g inkscape:label="Layer 1" inkscape:groupmode="layer" id="layer1">\n'
        '    <rect x="10" y="10" width="80" height="80" fill="blue"/>\n'
        "  </g>\n"
        '  <g inkscape:label="Layer 2" inkscape:groupmode="layer" id="layer2">\n'
        '    <circle cx="100" cy="100" r="40" fill="green"/>\n'
        "  </g>\n"
        "</svg>"
    )


@pytest.fixture
def shape_svg():
    """SVG with one rect, one circle, one text each with a unique id."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
        '  <rect id="rect1" x="10" y="10" width="60" height="40" fill="red"/>\n'
        '  <circle id="circle1" cx="100" cy="100" r="30" fill="blue"/>\n'
        '  <text id="text1" x="50" y="180">Hello</text>\n'
        "</svg>"
    )


@pytest.fixture
def gradient_svg():
    """SVG with an existing linearGradient in defs."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">\n'
        "  <defs>\n"
        '    <linearGradient id="lg1">\n'
        '      <stop offset="0%" stop-color="red"/>\n'
        '      <stop offset="100%" stop-color="blue"/>\n'
        "    </linearGradient>\n"
        "  </defs>\n"
        '  <rect x="0" y="0" width="200" height="200" fill="url(#lg1)"/>\n'
        "</svg>"
    )
