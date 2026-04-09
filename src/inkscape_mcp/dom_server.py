"""DOM-based Inkscape MCP server for SVG editing and cleaning."""

import io
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
from lxml import etree
from pydantic import BaseModel, field_validator
from scour.scour import generateDefaultOptions, scourString

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
_DANGEROUS_SVG_ELEMENTS = frozenset(
    {
        "script",
        "foreignObject",
        "object",
        "embed",
        "iframe",
    }
)

# Dangerous URI protocols to block in link-like attributes
_DANGEROUS_PROTOCOLS = ("javascript:", "vbscript:", "data:")

# Control characters that can disguise protocol strings (U+0000–U+001F, U+007F)
_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _strict_xml_check(text: str) -> None:
    """Pre-check SVG text for well-formedness and XXE hazards.

    Uses a hardened lxml parser with external entity resolution and DTD
    loading disabled.  Raises ValidationError on any XML syntax error.
    """
    strict_parser = etree.XMLParser(
        recover=False,
        no_network=True,
        resolve_entities=False,
        dtd_validation=False,
        load_dtd=False,
    )
    try:
        etree.fromstring(text.encode("utf-8"), parser=strict_parser)
    except etree.XMLSyntaxError as xml_err:
        raise ValidationError(f"Malformed XML: {xml_err}") from xml_err


def _validate_svg_attribute(name: str, value: str) -> None:
    """Raise ValueError if attribute name or value is unsafe to set.

    Blocks event-handler attributes (on*) and dangerous protocols in
    href/src/action attributes.  Called before every n.set() in dom_set.
    """
    if name.lower().startswith("on"):
        raise ValueError(f"Event handler attribute not allowed: {name}")
    # Normalize Clark notation ({ns}local) to local name for comparison
    local_name = name.split("}")[-1] if "}" in name else name
    if local_name in ("href", "xlink:href", "src", "action"):
        # Strip control characters that can disguise protocol strings
        sanitized = _CTRL_CHARS.sub("", value)
        val_lower = sanitized.lower().strip()
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
    # --- Remove dangerous elements ---
    # (collect first to avoid mutation-during-iteration)
    to_remove = [
        el
        for el in root.iter()
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


def _init_config(config: InkscapeConfig | None = None) -> None:
    """Initialize global configuration and semaphore."""
    global CFG, SEM
    if config is not None and CFG is config:
        return
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
        raise ValidationError("Path escapes workspace")
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


async def _dom_validate_impl(doc: Doc) -> dict:
    """Internal implementation for DOM validation."""
    if SEM is None:
        raise ToolError("Server not initialized")

    async with SEM:
        try:
            txt = _load_svg_text(doc)

            # Strict XML pre-check — inkex uses recover=True internally, so we
            # catch malformed XML here before it silently succeeds.
            _strict_xml_check(txt)

            # Full inkex-level validation (namespace, SVG structure)
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                inkex.load_svg(io.StringIO(txt))
            return {"ok": True}
        except ValidationError:
            raise
        except FileNotFoundError as e:
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

    # Create args object for internal use
    args = SetArgs(doc=doc, ops=ops, save_as=save_as)

    async with SEM:
        try:
            txt = _load_svg_text(args.doc)
            _strict_xml_check(txt)
            # Handle SVGs with XML declarations that require bytes input
            if txt.strip().startswith("<?xml") and "encoding=" in txt:
                # Convert to bytes for lxml parsing
                tree = inkex.load_svg(io.BytesIO(txt.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(txt))

            # Get the root element for CSS selection
            root = tree.getroot()
            changed = 0

            for op in args.ops:
                # Convert CSS selector to XPath with SVG namespace support
                selector = op.selector.value

                # Handle complex selectors by converting to XPath
                if selector == "circle":
                    xpath = "//svg:circle"
                elif selector == "rect":
                    xpath = "//svg:rect"
                elif selector == "text":
                    xpath = "//svg:text"
                elif selector == "*":
                    xpath = "//*"
                # SAFETY: SAFE_SEL regex ensures no quotes or XPath metacharacters
                elif selector.startswith("#"):
                    # ID selector: #myid -> //*[@id='myid']
                    xpath = f"//*[@id='{selector[1:]}']"
                elif selector.startswith(".") and "." not in selector[1:]:
                    # Simple class selector: .myclass
                    class_name = selector[1:]
                    xpath = f"//*[contains(concat(' ', @class, ' '), ' {class_name} ')]"
                elif "." in selector and not selector.startswith("."):
                    # Element with class: rect.shape ->
                    # //svg:rect[contains(concat(' ', @class, ' '), ' shape ')]
                    parts = selector.split(".", 1)
                    element, class_name = parts[0], parts[1]
                    xpath = (
                        f"//svg:{element}[contains(concat(' ', @class, ' '), "
                        f"' {class_name} ')]"
                    )
                elif "," in selector:
                    # Multiple selectors: text, rect -> //svg:text | //svg:rect
                    selectors = [s.strip() for s in selector.split(",")]
                    xpath_parts = []
                    for sel in selectors:
                        if sel in ("circle", "rect", "text"):
                            xpath_parts.append(f"//svg:{sel}")
                        else:
                            # Fallback for complex parts - just return no matches
                            xpath_parts.append("//NOMATCH")
                    xpath = " | ".join(xpath_parts)
                elif ">" in selector:
                    # Child selectors are complex - just return no matches
                    # for unsupported patterns
                    # This prevents the XPath error while keeping security
                    # validation working
                    xpath = "//NOMATCH"
                else:
                    # Simple element selector
                    if selector.isalpha():
                        xpath = f"//svg:{selector}"
                    else:
                        # Complex unsupported selector - return no matches
                        xpath = "//NOMATCH"

                nodes = root.xpath(
                    xpath, namespaces={"svg": "http://www.w3.org/2000/svg"}
                )
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
            # Use BytesIO for tree writing, then decode to string
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))

            return {"ok": True, "changed": changed, "out": str(out_path)}

        except ValidationError:
            raise
        except ValueError as e:
            raise ToolError(str(e)) from e
        except Exception as e:
            raise ToolError("DOM mutation failed") from e


@tool("dom_set")
async def dom_set(ctx: Context, doc: Doc, ops: list[SetOp], save_as: str) -> dict:
    """Set attributes/styles on DOM elements."""
    return await _dom_set_impl(doc, ops, save_as)


async def _dom_clean_impl(doc: Doc, save_as: str) -> dict:
    """Internal implementation for DOM cleaning."""
    if SEM is None:
        raise ToolError("Server not initialized")

    async with SEM:
        try:
            txt = _load_svg_text(doc)
            _strict_xml_check(txt)
            options = generateDefaultOptions()
            options.remove_metadata = True
            options.enable_viewboxing = True
            options.strip_comments = True
            options.remove_unreferenced_ids = True
            try:
                cleaned = scourString(txt, options=options)
            except Exception as e:
                raise ToolError("scour failed") from e

            # Re-parse and sanitize scour output before writing to disk
            if cleaned.strip().startswith("<?xml") and "encoding=" in cleaned:
                tree = inkex.load_svg(io.BytesIO(cleaned.encode("utf-8")))
            else:
                tree = inkex.load_svg(io.StringIO(cleaned))
            _sanitize_tree(tree.getroot())

            out_path = _ensure_in_workspace(Path(save_as))
            out_buf = io.BytesIO()
            tree.write(out_buf, encoding="utf-8", xml_declaration=True)
            _atomic_write(out_path, out_buf.getvalue().decode("utf-8"))
            return {"ok": True, "out": str(out_path)}

        except (ValidationError, ToolError):
            raise
        except Exception as e:
            raise ToolError("DOM clean failed") from e


@tool("dom_clean")
async def dom_clean(ctx: Context, doc: Doc, save_as: str) -> dict:
    """Clean SVG using scour optimizer."""
    return await _dom_clean_impl(doc, save_as)


def main(config: InkscapeConfig | None = None) -> None:
    """Main entry point for DOM server."""
    _init_config(config)
    app.run()


if __name__ == "__main__":
    main()
