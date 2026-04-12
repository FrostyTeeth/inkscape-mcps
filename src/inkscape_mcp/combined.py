"""Combined Inkscape MCP server with both CLI and DOM functionality."""

import logging
from collections.abc import Callable
from typing import Any, TypeVar, cast

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from . import cli_server, dom_server
from .auto_flatten import flatten_pydantic_params
from .config import InkscapeConfig

# Setup logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastMCP("inkscape-combined")

# Type-safe decorator cast for ty compatibility
F = TypeVar("F", bound=Callable[..., object])
tool: Callable[[str], Callable[[F], F]] = cast(Any, app.tool)

# Global config
CFG: InkscapeConfig | None = None


def _init_config(config: InkscapeConfig | None = None) -> None:
    """Initialize global configuration."""
    global CFG
    CFG = config or InkscapeConfig()


# Re-export CLI tools
@tool("action_list")
async def action_list(ctx: Context) -> dict:
    """List available Inkscape actions."""
    if CFG is None:
        raise ToolError("Config not initialized")
    cli_server._init_config(CFG)
    return await cli_server._action_list_impl()


@tool("action_run")
@flatten_pydantic_params
async def action_run(
    ctx: Context,
    doc: cli_server.Doc,
    actions: list[str] | None = None,
    export: cli_server.Export | None = None,
    timeout_s: int | None = None,
) -> dict:
    """Run Inkscape actions on a document."""
    logger.debug(f"action_run called with doc: {doc} (type: {type(doc)})")
    logger.debug(f"actions: {actions}, export: {export}, timeout_s: {timeout_s}")
    if CFG is None:
        raise ToolError("Config not initialized")
    cli_server._init_config(CFG)
    return await cli_server._action_run_impl(doc, actions, export, timeout_s)


# Re-export DOM tools
@tool("dom_validate")
@flatten_pydantic_params
async def dom_validate(ctx: Context, doc: dom_server.Doc) -> dict:
    """Validate SVG document structure."""
    logger.debug(f"dom_validate called with doc: {doc} (type: {type(doc)})")
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._dom_validate_impl(doc)


@tool("dom_set")
@flatten_pydantic_params
async def dom_set(
    ctx: Context, doc: dom_server.Doc, ops: list[dom_server.SetOp], save_as: str
) -> dict:
    """Set attributes/styles on DOM elements."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._dom_set_impl(doc, ops, save_as)


@tool("dom_clean")
@flatten_pydantic_params
async def dom_clean(ctx: Context, doc: dom_server.Doc, save_as: str) -> dict:
    """Clean SVG using scour optimizer."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._dom_clean_impl(doc, save_as)


@tool("create_shape")
@flatten_pydantic_params
async def create_shape(
    ctx: Context, doc: dom_server.Doc, shape: dom_server.ShapeSpec, save_as: str
) -> dict:
    """Append a new SVG shape element to the document root or a specified parent."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._create_shape_impl(doc, shape, save_as)


@tool("create_layer")
@flatten_pydantic_params
async def create_layer(
    ctx: Context, doc: dom_server.Doc, layer: dom_server.LayerSpec, save_as: str
) -> dict:
    """Append a new Inkscape layer (<g inkscape:groupmode="layer">) to the SVG."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._create_layer_impl(doc, layer, save_as)


@tool("rename_layer")
@flatten_pydantic_params
async def rename_layer(
    ctx: Context, doc: dom_server.Doc, layer_id: str, new_name: str, save_as: str
) -> dict:
    """Rename an Inkscape layer by updating its inkscape:label attribute."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._rename_layer_impl(doc, layer_id, new_name, save_as)


@tool("set_layer_visibility")
@flatten_pydantic_params
async def set_layer_visibility(
    ctx: Context, doc: dom_server.Doc, layer_id: str, visible: bool, save_as: str
) -> dict:
    """Set the visibility of an Inkscape layer by toggling display:none on its style."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._set_layer_visibility_impl(doc, layer_id, visible, save_as)


@tool("create_gradient")
@flatten_pydantic_params
async def create_gradient(
    ctx: Context, doc: dom_server.Doc, gradient: dom_server.GradientSpec, save_as: str
) -> dict:
    """Add a new linear or radial gradient to the SVG <defs> element."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._create_gradient_impl(doc, gradient, save_as)


@tool("duplicate_object")
@flatten_pydantic_params
async def duplicate_object(
    ctx: Context,
    doc: dom_server.Doc,
    source: dom_server.Selector,
    save_as: str,
    new_id: str | None = None,
    offset_dx: float = 0.0,
    offset_dy: float = 0.0,
) -> dict:
    """Duplicate an SVG element by CSS selector, inserting the copy after the original."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    args = dom_server.DuplicateArgs(
        source=source,
        new_id=new_id,
        offset_dx=offset_dx,
        offset_dy=offset_dy,
    )
    return await dom_server._duplicate_object_impl(doc, args, save_as)


@tool("query_dimensions")
@flatten_pydantic_params
async def query_dimensions(
    ctx: Context,
    doc: dom_server.Doc,
    selector: dom_server.Selector,
) -> dict:
    """Return width/height/bbox for SVG elements matching a CSS selector (read-only)."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    return await dom_server._query_dimensions_impl(doc, selector)


@tool("group_objects")
@flatten_pydantic_params
async def group_objects(
    ctx: Context,
    doc: dom_server.Doc,
    selectors: list[dom_server.Selector],
    save_as: str,
    group_id: str | None = None,
) -> dict:
    """Wrap all elements matching one or more CSS selectors in a new <g> element."""
    if CFG is None:
        raise ToolError("Config not initialized")
    dom_server._init_config(CFG)
    args = dom_server.GroupObjectsArgs(selectors=selectors, group_id=group_id)
    return await dom_server._group_objects_impl(doc, args, save_as)


def main(config: InkscapeConfig | None = None) -> None:
    """Main entry point for combined server."""
    _init_config(config)
    cli_server._resolve_inkscape_executable()  # Validate binary at startup; raises ToolError if not found
    app.run()


if __name__ == "__main__":
    main()
