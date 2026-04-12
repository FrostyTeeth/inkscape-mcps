"""DOM-based Inkscape MCP server for SVG editing and cleaning."""

import copy
import io
import math
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

import anyio
import inkex
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from pydantic import BaseModel, field_validator
from scour.scour import scourString

from .config import InkscapeConfig

app = FastMCP("inkex-dom")

# Type-safe decorator cast for ty compatibility
F = TypeVar("F", bound=Callable[..., object])
tool: Callable[[str], Callable[[F], F]] = cast(Any, app.tool)

# Global config and semaphore
CFG: InkscapeConfig | None = None
SEM: anyio.Semaphore | None = None

# Safe CSS selector pattern - simple subset
SAFE_SEL = re.compile(r"^[a-zA-Z0-9#.\-\s,>*]+$")

# Dangerous SVG element names (local, without namespace prefix)
_DANGEROUS_SVG_ELEMENTS = frozenset({
    "script", "foreignObject", "object", "embed", "iframe",
})

# Dangerous URI protocols to block in link-like attributes
_DANGEROUS_PROTOCOLS = ("javascript:", "vbscript:", "data:")


def _validate_svg_attribute(name: str, value: str) -> None:
    """Raise ValueError if attribute name or value is unsafe to set.

    Blocks event-handler attributes (on*) and dangerous protocols in
    href/src/action attributes.  Called before every n.set() in dom_set.
    """
    if name.lower().startswith("on"):
        raise ValueError(f"Event handler attribute not allowed: {name}")
    if name in ("href", "xlink:href", "src", "action"):
        val_lower = value.lower().strip()
        for proto in _DANGEROUS_PROTOCOLS:
            if val_lower.startswith(proto):
                raise ValueError(f"Dangerous protocol in attribute {name!r}")


def _sanitize_tree(root: inkex.SvgDocumentElement) -> None:
    """Strip dangerous elements and attributes from an SVG tree in-place.

    Removes <script>, <foreignObject>, <object>, <embed>, and <iframe>
    elements; strips all on* event-handler attributes; and removes
    javascript:/vbscript:/data: protocols from href/src values.
    Called before every write in _dom_set_impl so that pre-existing
    dangerous content in the source file cannot survive to disk.
    """
    # --- Remove dangerous elements (collect first to avoid mutation-during-iteration) ---
    to_remove = [
        el for el in root.iter()
        if (lambda tag: tag.split("}")[-1] if "}" in tag else tag)(el.tag)
        in _DANGEROUS_SVG_ELEMENTS
    ]
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    # --- Strip dangerous attributes from remaining elements ---
    for el in root.iter():
        attrs_to_delete = []
        for attr_name, attr_value in el.attrib.items():
            local = attr_name.split("}")[-1] if "}" in attr_name else attr_name
            if local.lower().startswith("on"):
                attrs_to_delete.append(attr_name)
            elif local in ("href", "src", "action"):
                val_lower = attr_value.lower().strip()
                if any(val_lower.startswith(p) for p in _DANGEROUS_PROTOCOLS):
                    attrs_to_delete.append(attr_name)
        for attr_name in attrs_to_delete:
            del el.attrib[attr_name]


# Unsafe patterns that should be blocked
UNSAFE_PATTERNS = [
    re.compile(r"//"),  # XPath syntax
    re.compile(r"script", re.IGNORECASE),  # Script tags/selectors
    re.compile(r"@import", re.IGNORECASE),  # CSS imports
    re.compile(r"expression\s*\(", re.IGNORECASE),  # CSS expressions
    re.compile(r"javascript:", re.IGNORECASE),  # JavaScript protocol
    re.compile(r"<\s*script", re.IGNORECASE),  # HTML script tags
    re.compile(r"url\s*\(", re.IGNORECASE),  # URL functions
    re.compile(r"\\\\"),  # Backslash escapes
    re.compile(r"[{}]"),  # Brace injection
]


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"
_SVG_NS = "http://www.w3.org/2000/svg"

# ---------------------------------------------------------------------------
# Shape creation allowlists
# All three frozensets are used by _validate_shape_spec and create_shape.
# ---------------------------------------------------------------------------
_ALLOWED_SHAPE_TAGS: frozenset[str] = frozenset(
    {"rect", "circle", "ellipse", "line", "polygon"}
)
_ALLOWED_SHAPE_ATTRS: frozenset[str] = frozenset(
    {
        "x", "y", "width", "height", "rx", "ry",
        "cx", "cy", "r",
        "x1", "y1", "x2", "y2",
        "points", "transform", "id", "class",
    }
)
_ALLOWED_STYLE_PROPS: frozenset[str] = frozenset(
    {
        "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
        "opacity", "fill-opacity", "stroke-opacity", "display", "visibility",
    }
)

# Valid XML ID regex: must start with letter or underscore, up to 64 chars total
_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")


def _validate_id(value: str) -> None:
    """Raise ValueError if *value* is not a safe XML/SVG id attribute value."""
    if not _ID_RE.match(value):
        raise ValueError(f"Invalid id value: {value!r}")


def _validate_numeric(
    value: float, *, min_val: float, max_val: float, name: str
) -> None:
    """Raise ValueError if *value* is non-finite or outside [min_val, max_val]."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if not (min_val <= value <= max_val):
        raise ValueError(
            f"{name} must be between {min_val} and {max_val}, got {value!r}"
        )


def _css_to_xpath(selector: str) -> str:
    """Convert a simple CSS selector to an XPath expression.

    Supports: element, #id, .class, element.class, *, comma lists,
    and child combinators (> — returned as //NOMATCH since unsupported).
    Complex or unsupported patterns also return //NOMATCH.
    """
    if selector == "*":
        return "//*"
    if selector.startswith("#"):
        return f"//*[@id='{selector[1:]}']"
    if selector.startswith(".") and "." not in selector[1:]:
        class_name = selector[1:]
        return f"//*[contains(concat(' ', @class, ' '), ' {class_name} ')]"
    if ">" in selector:
        return "//NOMATCH"
    if "," in selector:
        parts = [s.strip() for s in selector.split(",")]
        xpath_parts = []
        for part in parts:
            if part.isalpha():
                xpath_parts.append(f"//svg:{part}")
            else:
                xpath_parts.append("//NOMATCH")
        return " | ".join(xpath_parts)
    if "." in selector and not selector.startswith("."):
        element, class_name = selector.split(".", 1)
        return (
            f"//svg:{element}[contains(concat(' ', @class, ' '), ' {class_name} ')]"
        )
    if selector.isalpha():
        return f"//svg:{selector}"
    return "//NOMATCH"


def _select_nodes(root: inkex.SvgDocumentElement, selector_value: str) -> list:
    """Return all nodes matching *selector_value* (a CSS selector) under *root*."""
    xpath = _css_to_xpath(selector_value)
    return root.xpath(xpath, namespaces={"svg": "http://www.w3.org/2000/svg"})


def _init_config(config: InkscapeConfig | None = None) -> None:
    """Initialize global configuration and semaphore."""
    global CFG, SEM
    CFG = config or InkscapeConfig()
    SEM = anyio.Semaphore(CFG.max_concurrent)


def _ensure_in_workspace(p: Path) -> Path:
    """Ensure path is within workspace."""
    if CFG is None:
        raise ToolError("Config not initialized")

    # Resolve both paths to handle symlinks and platform-specific prefixes
    workspace_resolved = CFG.workspace.resolve()
    p_resolved = (CFG.workspace / p).resolve() if not p.is_absolute() else p.resolve()

    if not (
        p_resolved == workspace_resolved
        or str(p_resolved).startswith(str(workspace_resolved) + os.sep)
    ):
        raise ValidationError(
            "Path must be relative to the workspace directory "
            "(e.g. 'output.svg' or 'subdir/output.svg'), not an absolute or escaping path"
        )
    return p_resolved


def _read_bounded(p: Path) -> str:
    """Read file with size bounds checking."""
    if CFG is None:
        raise ToolError("Config not initialized")

    st = p.stat()
    if st.st_size > CFG.max_file_size:
        raise ValidationError("File too large")

    with open(p, encoding="utf-8") as f:
        return f.read()


class Doc(BaseModel):
    """Document specification."""

    type: Literal["file", "inline"]
    path: str | None = None
    svg: str | None = None


class Selector(BaseModel):
    """CSS selector for DOM operations."""

    type: Literal["css"]
    value: str

    @field_validator("value")
    @classmethod
    def _safe_css(cls, v: str) -> str:
        """Validate CSS selector is safe."""
        # Check for unsafe patterns first
        for pattern in UNSAFE_PATTERNS:
            if pattern.search(v):
                raise ValueError("Selector not allowed")

        # Then check basic format
        if not SAFE_SEL.match(v):
            raise ValueError("Selector not allowed")
        return v


class SetOp(BaseModel):
    """Set operation for DOM manipulation."""

    selector: Selector
    set: dict  # "@x": "10", "style.fill": "#f60", ...


class SetArgs(BaseModel):
    """Arguments for DOM set operations."""

    doc: Doc
    ops: list[SetOp]
    save_as: str  # path in workspace


def _load_svg_text(doc: Doc) -> str:
    """Load SVG text from document specification."""
    if CFG is None:
        raise ToolError("Config not initialized")

    if doc.type == "file":
        if not doc.path:
            raise ValidationError("Missing file path")
        p = _ensure_in_workspace(Path(doc.path))
        return _read_bounded(p)
    else:
        if doc.svg is None:
            raise ValidationError("Missing inline SVG")
        if len(doc.svg.encode("utf-8")) > CFG.max_file_size:
            raise ValidationError("Inline SVG too large")
        return doc.svg


def _atomic_write(path: Path, text: str) -> None:
    """Write file atomically using temporary file."""
    tmp = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex}")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------

def _name_is_safe(name: str) -> None:
    """Reject layer names with unsafe characters that could cause attribute injection."""
    if not name or len(name) > 80:
        raise ValidationError("Layer name must be 1-80 characters")
    if any(c in name for c in '<>"\'&\x00'):
        raise ValidationError("Layer name contains unsafe characters")


def _ensure_inkscape_namespace(root: inkex.SvgDocumentElement) -> None:
    """Ensure the Inkscape namespace is reachable from the document root.

    lxml manages namespace declarations automatically: when a child element is
    created with nsmap={"inkscape": INKSCAPE_NS} (as done in _create_layer_impl),
    the namespace is already scoped to that child.  This function is a no-op
    hook for future use; direct attrib mutation of xmlns: prefixes is not
    supported by lxml and is therefore intentionally avoided here.
    """
    # Namespace propagation is handled by lxml via the child nsmap; nothing
    # extra is needed here — the URI will appear in the serialised output.


# ---------------------------------------------------------------------------
# ShapeSpec model
# ---------------------------------------------------------------------------

class ShapeSpec(BaseModel):
    """Specification for a shape element to create."""

    kind: str
    attrs: dict = {}
    style: dict = {}
    id: str | None = None
    parent_selector: str | None = None


# ---------------------------------------------------------------------------
# Shape validation helper
# ---------------------------------------------------------------------------

def _validate_shape_spec(kind: str, attrs: dict, style: dict) -> None:
    """Validate shape kind, attrs, and style against allowlists.

    Raises ValueError if any value is not permitted.
    """
    if kind not in _ALLOWED_SHAPE_TAGS:
        raise ValueError(
            f"Shape kind {kind!r} is not allowed. "
            f"Allowed kinds: {sorted(_ALLOWED_SHAPE_TAGS)}"
        )

    for attr_name in attrs:
        if attr_name not in _ALLOWED_SHAPE_ATTRS:
            raise ValueError(
                f"Attribute {attr_name!r} is not allowed. "
                f"Allowed attrs: {sorted(_ALLOWED_SHAPE_ATTRS)}"
            )

    for prop_name in style:
        if prop_name not in _ALLOWED_STYLE_PROPS:
            raise ValueError(
                f"Style property {prop_name!r} is not allowed. "
                f"Allowed props: {sorted(_ALLOWED_STYLE_PROPS)}"
            )


async def _dom_validate_impl(doc: Doc) -> dict:
    """Internal implementation for DOM validation."""
    if SEM is None:
        raise ToolError("Server not initialized")

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            # Handle SVGs with XML declarations that require bytes input
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                # Convert to bytes for lxml parsing
                inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                inkex.load_svg(io.StringIO(txt))
            # Just verify we can load it - tree is unused but validates structure
            return {"ok": True}
        except ValidationError:
            # Re-raise validation errors (workspace, size limits, etc.) without wrapping
            raise
        except FileNotFoundError as e:
            # Re-raise file not found errors with descriptive message
            raise ValidationError("File not found") from e
        except Exception as e:
            raise ValidationError("ParseError") from e


@tool("dom_validate")
async def dom_validate(ctx: Context, doc: Doc) -> dict:
    """Validate SVG document structure."""
    return await _dom_validate_impl(doc)


async def _dom_set_impl(doc: Doc, ops: list[SetOp], save_as: str) -> dict:
    """Internal implementation for DOM set operations."""
    if SEM is None:
        raise ToolError("Server not initialized")

    args = SetArgs(doc=doc, ops=ops, save_as=save_as)

    async with SEM:
        try:
            txt = _load_svg_text(args.doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()
            changed = 0

            for op in args.ops:
                nodes = _select_nodes(root, op.selector.value)
                for n in nodes:
                    for k, v in op.set.items():
                        if k.startswith("style."):
                            st = n.style or inkex.Style()
                            st[k[6:]] = v
                            n.style = st
                        elif k.startswith("@"):
                            attr_name = k[1:]
                            attr_value = str(v)
                            _validate_svg_attribute(attr_name, attr_value)
                            n.set(attr_name, attr_value)
                    changed += 1

            _sanitize_tree(root)

            out_path = _ensure_in_workspace(Path(args.save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": changed, "out": str(out_path)}

        except ValidationError:
            raise
        except Exception as e:
            raise ToolError(f"DOM mutation failed: {e}") from e


@tool("dom_set")
async def dom_set(ctx: Context, doc: Doc, ops: list[SetOp], save_as: str) -> dict:
    """Set attributes/styles on DOM elements."""
    return await _dom_set_impl(doc, ops, save_as)


async def _dom_clean_impl(doc: Doc, save_as: str) -> dict:
    """Internal implementation for DOM cleaning."""
    if SEM is None:
        raise ToolError("Server not initialized")

    async with SEM:
        txt = _load_svg_text(doc)
        cleaned = scourString(
            txt, options={"remove_metadata": True, "enable_viewboxing": True}
        )
        out_path = _ensure_in_workspace(Path(save_as))
        _atomic_write(out_path, cleaned)
        return {"ok": True, "out": str(out_path)}


@tool("dom_clean")
async def dom_clean(ctx: Context, doc: Doc, save_as: str) -> dict:
    """Clean SVG using scour optimizer."""
    return await _dom_clean_impl(doc, save_as)


async def _create_shape_impl(doc: Doc, shape: ShapeSpec, save_as: str) -> dict:
    """Internal implementation for create_shape."""
    if SEM is None:
        raise ToolError("Server not initialized")

    # Validate shape spec
    try:
        _validate_shape_spec(shape.kind, shape.attrs, shape.style)
    except ValueError as e:
        raise ToolError(str(e)) from e

    # Validate/generate element id
    if shape.id is not None:
        try:
            _validate_id(shape.id)
        except ValueError as e:
            raise ToolError(str(e)) from e
        el_id = shape.id
    else:
        el_id = f"shape-{uuid.uuid4().hex[:8]}"

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()

            # Find parent element
            if shape.parent_selector is not None:
                nodes = _select_nodes(root, shape.parent_selector)
                if not nodes:
                    raise ToolError(
                        f"No element found for parent_selector: {shape.parent_selector!r}"
                    )
                parent = nodes[0]
            else:
                parent = root

            # Create the new element
            el = root.makeelement(f"{{{_SVG_NS}}}{shape.kind}", {})

            # Set attributes
            for attr_name, attr_value in shape.attrs.items():
                str_val = str(attr_value)
                _validate_svg_attribute(attr_name, str_val)
                el.set(attr_name, str_val)

            # Set style
            if shape.style:
                style_str = ";".join(
                    f"{k}:{v}" for k, v in shape.style.items()
                )
                el.set("style", style_str)

            # Set id
            el.set("id", el_id)

            # Append to parent
            parent.append(el)

            # Sanitize and write
            _sanitize_tree(root)

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": el_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"create_shape failed: {e}") from e


@tool("create_shape")
async def create_shape(ctx: Context, doc: Doc, shape: ShapeSpec, save_as: str) -> dict:
    """Append a new SVG shape element to the document root or a specified parent."""
    return await _create_shape_impl(doc, shape, save_as)


# ---------------------------------------------------------------------------
# LayerSpec model
# ---------------------------------------------------------------------------

class LayerSpec(BaseModel):
    """Specification for an Inkscape layer (<g inkscape:groupmode="layer">)."""

    name: str
    id: str | None = None
    parent_id: str | None = None  # nest into an existing layer


async def _create_layer_impl(doc: Doc, layer: LayerSpec, save_as: str) -> dict:
    """Internal implementation for create_layer."""
    if SEM is None:
        raise ToolError("Server not initialized")

    # Validate inputs before acquiring the semaphore
    _name_is_safe(layer.name)
    if layer.id is not None:
        try:
            _validate_id(layer.id)
        except ValueError as e:
            raise ToolError(str(e)) from e
    if layer.parent_id is not None:
        try:
            _validate_id(layer.parent_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()

            # Check for duplicate id
            # layer.id has been validated with _validate_id so f-string is safe
            if layer.id is not None:
                existing = root.xpath(f"//*[@id='{layer.id}']")
                if existing:
                    raise ValidationError(
                        f"Element with id {layer.id!r} already exists"
                    )

            # Find parent element
            # layer.parent_id has been validated with _validate_id so f-string is safe
            if layer.parent_id is not None:
                matches = root.xpath(f"//*[@id='{layer.parent_id}']")
                if not matches:
                    raise ValidationError(
                        f"Parent element with id {layer.parent_id!r} not found"
                    )
                parent = matches[0]
            else:
                parent = root

            # Build the layer <g> element
            layer_id = layer.id if layer.id is not None else f"layer-{uuid.uuid4().hex[:8]}"
            g = root.makeelement(
                f"{{{_SVG_NS}}}g",
                nsmap={"inkscape": INKSCAPE_NS},
            )
            g.set("id", layer_id)
            g.set(f"{{{INKSCAPE_NS}}}groupmode", "layer")
            g.set(f"{{{INKSCAPE_NS}}}label", layer.name)

            parent.append(g)
            _ensure_inkscape_namespace(root)

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": layer_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"create_layer failed: {e}") from e


@tool("create_layer")
async def create_layer(ctx: Context, doc: Doc, layer: LayerSpec, save_as: str) -> dict:
    """Append a new Inkscape layer (<g inkscape:groupmode="layer">) to the SVG."""
    return await _create_layer_impl(doc, layer, save_as)


# ---------------------------------------------------------------------------
# rename_layer helpers and implementation
# ---------------------------------------------------------------------------

def _find_layer_by_id(root: inkex.SvgDocumentElement, layer_id: str):
    """Find a <g> element that is an Inkscape layer with the given id.

    Returns the element or raises ValidationError.
    Calls _validate_id first to ensure layer_id is safe before use in XPath.
    """
    try:
        _validate_id(layer_id)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    # id is validated — f-string interpolation into XPath is safe
    matches = root.xpath(f"//*[@id='{layer_id}']")
    if not matches:
        raise ValidationError(f"Layer '{layer_id}' not found")
    el = matches[0]

    groupmode_attr = f"{{{INKSCAPE_NS}}}groupmode"
    if el.get(groupmode_attr) != "layer":
        raise ValidationError(f"Element '{layer_id}' is not an Inkscape layer")

    return el


class RenameLayerArgs(BaseModel):
    """Arguments for rename_layer."""

    layer_id: str
    new_name: str


async def _rename_layer_impl(
    doc: Doc, layer_id: str, new_name: str, save_as: str
) -> dict:
    """Internal implementation for rename_layer."""
    if SEM is None:
        raise ToolError("Server not initialized")

    _name_is_safe(new_name)

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()
            el = _find_layer_by_id(root, layer_id)

            label_attr = f"{{{INKSCAPE_NS}}}label"
            el.set(label_attr, new_name)

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": layer_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"rename_layer failed: {e}") from e


@tool("rename_layer")
async def rename_layer(
    ctx: Context, doc: Doc, layer_id: str, new_name: str, save_as: str
) -> dict:
    """Rename an Inkscape layer by updating its inkscape:label attribute."""
    return await _rename_layer_impl(doc, layer_id, new_name, save_as)


# ---------------------------------------------------------------------------
# set_layer_visibility helpers and implementation
# ---------------------------------------------------------------------------

class LayerVisibilityArgs(BaseModel):
    """Arguments for set_layer_visibility."""

    layer_id: str
    visible: bool


async def _set_layer_visibility_impl(
    doc: Doc, layer_id: str, visible: bool, save_as: str
) -> dict:
    """Internal implementation for set_layer_visibility."""
    if SEM is None:
        raise ToolError("Server not initialized")

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()
            el = _find_layer_by_id(root, layer_id)

            # Parse existing style using inkex.Style
            existing_style_str = el.get("style", "")
            style = inkex.Style(existing_style_str)

            if visible:
                # Remove display:none if present
                style.pop("display", None)
            else:
                # Set display:none
                style["display"] = "none"

            # Write back — only set if style is non-empty, else remove attr
            if style:
                el.set("style", str(style))
            elif "style" in el.attrib:
                del el.attrib["style"]

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": layer_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"set_layer_visibility failed: {e}") from e


@tool("set_layer_visibility")
async def set_layer_visibility(
    ctx: Context, doc: Doc, layer_id: str, visible: bool, save_as: str
) -> dict:
    """Set the visibility of an Inkscape layer by toggling display:none on its style."""
    return await _set_layer_visibility_impl(doc, layer_id, visible, save_as)


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

_COLOR_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")


def _validate_color_hex(value: str) -> str:
    """Raise ValidationError if *value* is not a 3- or 6-digit hex color."""
    if not _COLOR_HEX_RE.match(value):
        raise ValidationError(
            f"Color must be #rgb or #rrggbb hex, got: {value!r}"
        )
    return value


def _ensure_defs(root: inkex.SvgDocumentElement) -> inkex.BaseElement:
    """Find or create the <svg:defs> element as first child of root."""
    defs_tag = f"{{{_SVG_NS}}}defs"
    defs = root.find(defs_tag)
    if defs is None:
        defs = root.makeelement(defs_tag, {})
        root.insert(0, defs)
    return defs


# ---------------------------------------------------------------------------
# GradientStop / GradientSpec models
# ---------------------------------------------------------------------------

class GradientStop(BaseModel):
    """A single color stop in a gradient."""

    offset: float           # 0.0..1.0
    color: str              # "#rrggbb" or "#rgb" only
    opacity: float = 1.0    # 0.0..1.0


class GradientSpec(BaseModel):
    """Specification for a new SVG gradient element."""

    kind: Literal["linear", "radial"]
    id: str | None = None
    stops: list[GradientStop]   # 2..16
    # linear coords (all optional — default SVG behavior if None)
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    # radial coords
    cx: float | None = None
    cy: float | None = None
    r: float | None = None


async def _create_gradient_impl(
    doc: Doc, gradient: GradientSpec, save_as: str
) -> dict:
    """Internal implementation for create_gradient."""
    if SEM is None:
        raise ToolError("Server not initialized")

    # Validate stops count
    if len(gradient.stops) < 2:
        raise ValidationError("gradient requires at least 2 stops")
    if len(gradient.stops) > 16:
        raise ValidationError("gradient has too many stops (max 16)")

    # Validate each stop
    for stop in gradient.stops:
        _validate_color_hex(stop.color)
        if not (0.0 <= stop.offset <= 1.0):
            raise ValidationError(
                f"stop offset must be 0.0..1.0, got {stop.offset}"
            )
        if not (0.0 <= stop.opacity <= 1.0):
            raise ValidationError(
                f"stop opacity must be 0.0..1.0, got {stop.opacity}"
            )

    # Validate id if provided
    if gradient.id is not None:
        try:
            _validate_id(gradient.id)
        except ValueError as e:
            raise ValidationError(str(e)) from e

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()
            defs = _ensure_defs(root)

            # Choose tag
            if gradient.kind == "linear":
                grad_tag = f"{{{_SVG_NS}}}linearGradient"
            else:
                grad_tag = f"{{{_SVG_NS}}}radialGradient"

            grad_id = (
                gradient.id if gradient.id is not None
                else f"gradient-{uuid.uuid4().hex[:8]}"
            )
            grad_el = root.makeelement(grad_tag, {"id": grad_id})

            # Set coordinate attrs if provided
            coord_pairs = [
                ("x1", gradient.x1),
                ("y1", gradient.y1),
                ("x2", gradient.x2),
                ("y2", gradient.y2),
                ("cx", gradient.cx),
                ("cy", gradient.cy),
                ("r", gradient.r),
            ]
            for attr_name, val in coord_pairs:
                if val is not None:
                    grad_el.set(attr_name, str(val))

            # Build stop elements
            stop_tag = f"{{{_SVG_NS}}}stop"
            for stop in gradient.stops:
                stop_el = root.makeelement(stop_tag, {})
                stop_el.set("offset", str(stop.offset))
                stop_el.set(
                    "style",
                    f"stop-color:{stop.color};stop-opacity:{stop.opacity}",
                )
                grad_el.append(stop_el)

            defs.append(grad_el)

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": grad_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"create_gradient failed: {e}") from e


@tool("create_gradient")
async def create_gradient(
    ctx: Context, doc: Doc, gradient: GradientSpec, save_as: str
) -> dict:
    """Add a new linear or radial gradient to the SVG <defs> element."""
    return await _create_gradient_impl(doc, gradient, save_as)


# ---------------------------------------------------------------------------
# duplicate_object helpers, model, and implementation
# ---------------------------------------------------------------------------

def _append_transform(el, extra: str) -> None:
    """Append a transform to an element, preserving any existing transform."""
    existing = el.get("transform", "")
    if existing:
        el.set("transform", f"{existing} {extra}")
    else:
        el.set("transform", extra)


class DuplicateArgs(BaseModel):
    """Arguments for duplicate_object."""

    source: Selector
    new_id: str | None = None
    offset_dx: float = 0.0
    offset_dy: float = 0.0


async def _duplicate_object_impl(
    doc: Doc, args: DuplicateArgs, save_as: str
) -> dict:
    """Internal implementation for duplicate_object."""
    if SEM is None:
        raise ToolError("Server not initialized")

    # Validate new_id before acquiring the semaphore
    if args.new_id is not None:
        try:
            _validate_id(args.new_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            root = tree.getroot()
            matches = _select_nodes(root, args.source.value)

            if not matches:
                return {"ok": True, "changed": 0, "out": None, "id": None}

            original = matches[0]

            # Deep copy the element (includes all children)
            copy_el = copy.deepcopy(original)

            # Assign id
            new_id = args.new_id if args.new_id else f"copy-{uuid.uuid4().hex[:8]}"
            copy_el.set("id", new_id)

            # Apply offset transform if non-zero
            if args.offset_dx != 0.0 or args.offset_dy != 0.0:
                _append_transform(
                    copy_el,
                    f"translate({args.offset_dx},{args.offset_dy})",
                )

            # Insert copy immediately after original in the tree
            original.addnext(copy_el)

            # Sanitize before writing (strips <script>, on* handlers, etc.)
            _sanitize_tree(root)

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": 1, "out": str(out_path), "id": new_id}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError(f"duplicate_object failed: {e}") from e


@tool("duplicate_object")
async def duplicate_object(
    ctx: Context,
    doc: Doc,
    source: Selector,
    save_as: str,
    new_id: str | None = None,
    offset_dx: float = 0.0,
    offset_dy: float = 0.0,
) -> dict:
    """Duplicate an SVG element by CSS selector, inserting the copy after the original."""
    args = DuplicateArgs(
        source=source,
        new_id=new_id,
        offset_dx=offset_dx,
        offset_dy=offset_dy,
    )
    return await _duplicate_object_impl(doc, args, save_as)


def main(config: InkscapeConfig | None = None) -> None:
    """Main entry point for DOM server."""
    _init_config(config)
    app.run()


if __name__ == "__main__":
    main()
