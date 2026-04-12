# TDD Plan: Missing Tools for Inkscape MCP Server

## Overview

Add eight new tools to `inkscape-mcp-dom` (and re-export through `combined`)
for procedural SVG authoring and inspection: `create_shape`, `create_layer`,
`rename_layer`, `set_layer_visibility`, `duplicate_object`, `create_gradient`,
`query_dimensions`, and `group_objects`. All tools reuse the existing
security model (CSS selector validation, attribute/protocol allowlists,
workspace confinement, atomic writes, `_sanitize_tree` on save). Tools are
added strictly TDD: red test, minimal green, then refactor.

## Scope

- **In scope:** New DOM-layer tools that read/write SVG via `inkex`. CLI
  re-exports through `combined.py`. Unit + integration tests.
- **Out of scope:** New `inkscape` CLI actions, GUI interactions, new
  Pydantic auto-flatten behavior, cross-submodule changes.

## Architecture Conventions (discovered, must be followed)

1. Tool implementations live in `src/inkscape_mcp/dom_server.py` as
   `async def _<name>_impl(...)` + a thin `@tool("<name>")` wrapper. The
   combined server in `src/inkscape_mcp/combined.py` re-exports each tool
   with `@flatten_pydantic_params` so MCP clients see flat args (e.g.
   `doc_type`, `doc_path`, `ops_json`).
2. Every public entry point guards on `SEM is None` / `CFG is None` and
   runs the real work inside `async with SEM:`.
3. SVG input comes from `Doc` (`type: "file" | "inline"`). Use
   `_load_svg_text(doc)`; parse via `inkex.load_svg(io.StringIO(...))` or
   `io.BytesIO(...)` when the source starts with `<?xml ... encoding=`.
4. All writes go through `_ensure_in_workspace(Path(save_as))` then
   `_atomic_write(path, text)`. Before writing, `_sanitize_tree(root)` is
   called to strip `<script>`, `<foreignObject>`, `on*` handlers, and
   dangerous URI protocols from pre-existing content.
5. Every attribute set must pass through `_validate_svg_attribute(name, value)`
   before `el.set(name, value)` or `el.attrib[name] = value`.
6. CSS selectors go through `Selector` (pydantic), which rejects unsafe
   patterns in `UNSAFE_PATTERNS` and enforces `SAFE_SEL`. The CSS→XPath
   conversion already in `_dom_set_impl` must be **extracted** to a helper
   (`_css_to_xpath(selector: str) -> str`) before the first new tool lands,
   so all new tools reuse one code path (see Phase 0 refactor).
7. Tests live in `tests/` as `test_<area>_integration.py` using the
   `fastmcp.Client(app)` pattern with `temp_workspace`/`test_config`
   fixtures. Security-boundary tests live in `tests/test_security_boundaries.py`
   and call the **combined** app so flattened args are exercised
   (`doc_type`/`doc_svg` rather than nested `doc`).
8. Return shape for mutation tools is
   `{"ok": True, "changed": <int>, "out": "<abs path>"}`. Query tools
   return a structured dict (see `query_dimensions` below). The `"ok"`
   key is mandatory.

## Affected Files

- `src/inkscape_mcp/dom_server.py` — new impls + helpers, new Pydantic models
- `src/inkscape_mcp/combined.py` — re-exports with `@flatten_pydantic_params`
- `tests/test_dom_server_integration.py` — happy-path + DOM-level tests
- `tests/test_combined_server_integration.py` — combined re-export smoke tests
- `tests/test_security_boundaries.py` — selector/attribute/path security tests
- `tests/conftest.py` **(new)** — shared fixtures extracted from the three
  current test files (see "Shared Fixtures" below)

## Shared Fixtures (build once, reuse everywhere)

Create `tests/conftest.py`:

- `temp_workspace` — `tempfile.TemporaryDirectory()` → `Path` (move from
  the three test files)
- `dom_test_config(temp_workspace)` — `InkscapeConfig` wired into
  `dom_server._init_config`; returns config
- `combined_test_config(temp_workspace)` — same but wired into
  `combined._init_config`
- `base_svg` — minimal parseable SVG with xmlns and viewBox
- `layered_svg` — SVG containing two Inkscape layers
  (`<g inkscape:groupmode="layer" inkscape:label="Layer 1" id="layer1">`)
  for layer-tool tests. Must declare `xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"`.
- `shape_svg` — SVG with one rect, one circle, one text, each with an id
- `gradient_svg` — SVG with an existing `<defs><linearGradient id="lg1">`
  so duplicate/query tests have a known-good defs section
- `write_svg(workspace, name, content)` helper — writes and returns
  absolute Path

## Cross-Cutting Helpers to Add (Phase 0, before any tool)

All in `dom_server.py`:

1. `INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"` and
   `SODIPODI_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd"`
2. `_css_to_xpath(selector: str) -> str` — extract the selector→xpath
   logic currently inlined in `_dom_set_impl`. Must preserve existing
   behavior (unit tests required).
3. `_select_nodes(root, selector_value: str) -> list` — calls
   `_css_to_xpath` and executes `root.xpath(..., namespaces={...})`.
4. `_load_tree(doc: Doc) -> tuple[ElementTree, Element]` — handles the
   `<?xml` + `encoding=` branch once, returns `(tree, root)`.
5. `_write_tree(tree, save_as: str) -> Path` — runs `_sanitize_tree(root)`,
   `_ensure_in_workspace`, `tree.write(BytesIO)`, `_atomic_write`, returns
   final path.
6. `_new_svg_element(root, tag: str, attribs: dict[str, str]) -> Element` —
   creates `{http://www.w3.org/2000/svg}<tag>` via `root.makeelement` and
   sets each attribute through `_validate_svg_attribute`.
7. `_ALLOWED_SHAPE_TAGS = frozenset({"rect", "circle", "ellipse", "line", "polygon"})`
8. `_ALLOWED_SHAPE_ATTRS = frozenset({
       "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r",
       "x1", "y1", "x2", "y2", "points", "transform", "id", "class",
   })` (fill/stroke go through `style.*` not raw attrs)
9. `_ALLOWED_STYLE_PROPS = frozenset({
       "fill", "stroke", "stroke-width", "stroke-linecap",
       "stroke-linejoin", "opacity", "fill-opacity", "stroke-opacity",
       "display", "visibility",
   })`
10. `_validate_id(value: str) -> None` — regex
    `^[A-Za-z_][A-Za-z0-9_-]{0,63}$`, raises `ValidationError` otherwise.
    Prevents XML id injection and unbounded strings.
11. `_validate_numeric(value: float, *, min_val: float, max_val: float, name: str) -> None`
    — enforces finite float within explicit bounds.

## TDD Workflow for Every Tool

For each tool, follow **RED → GREEN → REFACTOR** in that order. Every
commit must contain either only new failing tests, or only code that
turns previously-red tests green.

---

## Phase 0: Helpers + Refactor of Existing dom_set

### 0.1 RED — extract `_css_to_xpath` tests
- File: `tests/test_dom_helpers.py` **(new)**
- Tests (unit, no fastmcp client):
  - `test_css_to_xpath_simple_element` → `"circle"` → `"//svg:circle"`
  - `test_css_to_xpath_id` → `"#circle1"` → `"//*[@id='circle1']"`
  - `test_css_to_xpath_class` → `".shape"` → contains
    `"contains(concat(' ', @class, ' '), ' shape ')"`
  - `test_css_to_xpath_element_class` → `"rect.shape"` → scoped to rect
  - `test_css_to_xpath_wildcard` → `"*"` → `"//*"`
  - `test_css_to_xpath_nomatch_for_unsupported` → `"circle > rect"` →
    `"//NOMATCH"`
  - `test_validate_id_accepts_safe` (`"myId"`, `"layer-1"`, `"_under"`)
  - `test_validate_id_rejects_unsafe` (`""`, `"1bad"`, `"x y"`, `"a" * 100`,
    `"<script>"`)
- All tests red because helpers do not exist yet.

### 0.2 GREEN
- Extract existing CSS→XPath block from `_dom_set_impl` into
  `_css_to_xpath`. Implement `_validate_id`. Update `_dom_set_impl` to
  call the helper. Run full test suite to confirm nothing regressed.

### 0.3 REFACTOR
- Ensure `_dom_set_impl` is now < 40 lines.
- Verify `test_dom_server_integration.py` still passes unchanged.

---

## Phase 1: `create_shape`

Procedurally append a rect/circle/ellipse/line/polygon to the SVG root
(or to a caller-specified parent selector) with fill/stroke styling.

### Pydantic models (in `dom_server.py`)
```python
class ShapeSpec(BaseModel):
    kind: Literal["rect", "circle", "ellipse", "line", "polygon"]
    attrs: dict[str, float | int | str]  # e.g. {"x": 10, "y": 20, "width": 100}
    style: dict[str, str] = Field(default_factory=dict)  # fill/stroke/etc
    id: str | None = None
    parent: Selector | None = None  # default: svg root
```

### 1.1 RED — tests in `tests/test_dom_create_shape.py` **(new)**
- `test_create_rect_appends_rect_to_root` — given `base_svg`, call tool,
  assert output XML contains `<rect x="10" y="10" width="50" height="30"
  style="fill:#ff0000">` and `result.data["changed"] == 1`.
- `test_create_circle_with_stroke` — verify both `fill` and `stroke-width`
  land in `style=`.
- `test_create_ellipse_rx_ry` — verify `rx`/`ry` attrs.
- `test_create_line_x1y1x2y2` — verify all four coords.
- `test_create_polygon_points` — verify `points="0,0 10,10 20,0"`.
- `test_create_shape_with_parent_selector` — parent `#group1` → shape
  appended inside that group, not root.
- `test_create_shape_returns_generated_id` — when `id` not supplied,
  tool returns an auto-generated id in `result.data["id"]` that matches
  `_validate_id`.
- **Edge cases:**
  - `test_create_shape_rejects_unknown_kind` → `"spiral"` raises.
  - `test_create_shape_rejects_non_numeric_width` → `"width": "10px;)"`
    raises (coerce to float, catch ValueError).
  - `test_create_shape_rejects_negative_width` → bounded check.
  - `test_create_shape_rejects_unknown_attr` → `"onmouseover"` raises.
  - `test_create_shape_rejects_unknown_style_prop` → `"behavior": "url()"` raises.
  - `test_create_shape_rejects_unsafe_id` → `"<script>"` raises.
  - `test_create_shape_parent_not_found_returns_changed_zero` (no match
    → no mutation, no write).

### 1.2 GREEN — implementation sketch
```python
async def _create_shape_impl(doc: Doc, shape: ShapeSpec, save_as: str) -> dict:
    if SEM is None: raise ToolError(...)
    async with SEM:
        if shape.kind not in _ALLOWED_SHAPE_TAGS:
            raise ValidationError(f"Unknown shape kind: {shape.kind}")
        # Validate every attr key is in _ALLOWED_SHAPE_ATTRS
        # Validate every style key is in _ALLOWED_STYLE_PROPS
        # Coerce numeric values via _validate_numeric
        # Validate id if provided, else generate "shape-<uuid4 hex[:8]>"
        tree, root = _load_tree(doc)
        parent = root
        if shape.parent:
            matches = _select_nodes(root, shape.parent.value)
            if not matches:
                return {"ok": True, "changed": 0, "out": None, "id": None}
            parent = matches[0]
        el = _new_svg_element(root, shape.kind, {...attrs...})
        if shape.style:
            el.set("style", _style_dict_to_str(shape.style))
        parent.append(el)
        out = _write_tree(tree, save_as)
        return {"ok": True, "changed": 1, "out": str(out), "id": el.get("id")}
```
Register as `@tool("create_shape")` in `dom_server.py`; re-export in
`combined.py` with `@flatten_pydantic_params`.

### 1.3 REFACTOR
- Move shape validation to `_validate_shape_spec(spec: ShapeSpec)`.
- Run `test_dom_helpers.py` plus new test file.

### 1.4 Safety considerations
- Shape tag allowlist prevents `<script>`/`<foreignObject>` injection.
- Attr allowlist blocks `href`, `onclick`, etc.
- Style prop allowlist blocks `behavior`, `-moz-binding`.
- Numeric coercion + bounds stop unbounded strings.
- Every attribute still passes through `_validate_svg_attribute`.
- `_sanitize_tree` runs on every write (already in `_write_tree`).

---

## Phase 2: `create_layer`

### Model
```python
class LayerSpec(BaseModel):
    name: str          # Inkscape label (display name)
    id: str | None = None
    parent_id: str | None = None  # nest into existing layer
```

### 2.1 RED — `tests/test_dom_layers.py` **(new)**
- `test_create_layer_appends_g_with_inkscape_groupmode` — output contains
  `inkscape:groupmode="layer"` and `inkscape:label="<name>"`.
- `test_create_layer_auto_id_when_absent` — id matches `_validate_id`
  regex, returned in `result.data["id"]`.
- `test_create_layer_explicit_id` — uses provided id.
- `test_create_layer_nested_under_parent_id` — new layer appears as
  child of the layer whose id matches `parent_id`.
- `test_create_layer_ensures_inkscape_namespace_declared` — root element
  must have `xmlns:inkscape` after save; add it if absent.
- **Edge cases:**
  - `test_create_layer_rejects_duplicate_id` — raises if id already used.
  - `test_create_layer_rejects_unsafe_name` — name containing
    `<`, `>`, or `"` is rejected (prevents attribute injection via label).
  - `test_create_layer_rejects_unsafe_id` — id must pass `_validate_id`.
  - `test_create_layer_parent_not_found_raises` — clear error.

### 2.2 GREEN
- Implement `_create_layer_impl`: build a `<g>` element with
  `{INKSCAPE_NS}groupmode = "layer"` and `{INKSCAPE_NS}label = name`.
  Use `_validate_svg_attribute` on every set (label must pass as a normal
  attribute — it does not start with `on` and is not a URI attr).
- Add `_ensure_inkscape_namespace(root)` helper that sets
  `nsmap` via `etree.register_namespace`/root.attrib update only if absent.
- Register `@tool("create_layer")` + combined re-export.

### 2.3 REFACTOR
- Extract `_name_is_safe(name: str)` with rules: length 1..80, no
  control chars, no `<>"'&`.

### 2.4 Safety considerations
- Inkscape label injected as attribute value, but we reject `"<>&"` to
  belt-and-brace against lxml mis-serialization.
- Reuses `_validate_id` and `_validate_svg_attribute`.
- Only `<g>` with safe attrs is appended — no user-controlled tag.

---

## Phase 3: `rename_layer`

### Model
```python
class RenameLayerArgs(BaseModel):
    layer_id: str    # target layer's svg id
    new_name: str    # new inkscape:label
```

### 3.1 RED
- `test_rename_layer_updates_inkscape_label` — given `layered_svg`, after
  rename the target layer's `inkscape:label` == new name and
  `result.data["changed"] == 1`.
- `test_rename_layer_leaves_other_layers_alone`.
- `test_rename_layer_preserves_id` — id unchanged.
- `test_rename_layer_not_found_raises` — missing layer → `ValidationError`.
- `test_rename_layer_rejects_non_layer_group` — a `<g>` without
  `inkscape:groupmode="layer"` is rejected (prevents renaming arbitrary
  groups that happen to have the requested id).
- `test_rename_layer_rejects_unsafe_name`.
- `test_rename_layer_rejects_unsafe_id`.

### 3.2 GREEN
- Implement `_rename_layer_impl`:
  - Validate inputs, load tree.
  - `xpath` for `//svg:g[@id=$id and @inkscape:groupmode='layer']`
    (pass id via lxml variable binding — do **not** f-string user input
    into XPath).
  - Raise `ValidationError("Layer not found")` if empty.
  - Set `{INKSCAPE_NS}label` via `_validate_svg_attribute`.
  - Write tree via `_write_tree`.

### 3.3 REFACTOR
- Extract `_find_layer_by_id(root, layer_id) -> Element` helper; reused
  by `set_layer_visibility`.

### 3.4 Safety considerations
- XPath parameterization (not string concat) is mandatory.
- Only mutates groups explicitly marked as Inkscape layers.
- Name validation identical to Phase 2.

---

## Phase 4: `set_layer_visibility`

### Model
```python
class LayerVisibilityArgs(BaseModel):
    layer_id: str
    visible: bool
```

### 4.1 RED
- `test_set_layer_visibility_hide` — `visible=False` → output has
  `display:none` in `style`, returns `changed=1`.
- `test_set_layer_visibility_show_clears_display_none` — starting with
  `style="display:none"`, set `visible=True` → style no longer contains
  `display:none`.
- `test_set_layer_visibility_preserves_other_style_props` — a layer with
  `style="display:none;opacity:0.5"` keeps opacity after show.
- `test_set_layer_visibility_not_found_raises`.
- `test_set_layer_visibility_rejects_non_layer_group`.

### 4.2 GREEN
- Reuse `_find_layer_by_id`.
- Manipulate style via `inkex.Style` (same pattern as `_dom_set_impl`),
  setting/removing only the `display` key.

### 4.3 REFACTOR
- Extract `_set_style_prop(el, key, value)` / `_remove_style_prop(el, key)`
  for reuse by later tools.

### 4.4 Safety considerations
- Only mutates the `display` property. No general attribute write.
- Same layer-only constraint as rename.

---

## Phase 5: `create_gradient`

**Ordering: must land before any tool that references gradients by id,
which is currently none — but `create_shape` tests for "use gradient as
fill" should only be added *after* this phase.**

### Models
```python
class GradientStop(BaseModel):
    offset: float       # 0.0..1.0
    color: str          # "#rrggbb" or "#rgb"
    opacity: float = 1.0  # 0.0..1.0

class GradientSpec(BaseModel):
    kind: Literal["linear", "radial"]
    id: str | None = None
    stops: list[GradientStop]  # 2..16
    # linear coords
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    # radial coords
    cx: float | None = None
    cy: float | None = None
    r: float | None = None
```

### 5.1 RED — `tests/test_dom_gradient.py` **(new)**
- `test_create_linear_gradient_adds_to_defs` — output contains
  `<linearGradient id="...">` inside `<defs>`, with two `<stop>` children.
- `test_create_radial_gradient_adds_to_defs`.
- `test_create_gradient_creates_defs_if_missing` — input SVG without
  `<defs>` → `<defs>` is created.
- `test_create_gradient_returns_id_for_reuse` — `result.data["id"]`
  equals attr id and is url-safe.
- `test_create_gradient_stop_colors_are_hex_only` — reject `"red"`,
  `"rgb(1,2,3)"`, `"url(x)"`.
- `test_create_gradient_rejects_too_few_stops` — 0 or 1 stop.
- `test_create_gradient_rejects_too_many_stops` — 17 stops.
- `test_create_gradient_rejects_offset_out_of_range` — `1.5`, `-0.1`.
- `test_create_gradient_rejects_unsafe_id`.
- `test_create_gradient_linear_requires_x1y1x2y2` (or allow all-None for
  default SVG behavior — choose and test explicitly).
- `test_create_gradient_radial_requires_cxcyr`.

### 5.2 GREEN
- `_COLOR_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")`
- `_create_gradient_impl`: validate, load tree, find or create
  `svg:defs` (first child), build `<linearGradient>`/`<radialGradient>`
  with id, append `<stop offset="..." style="stop-color:...;stop-opacity:...">` children.
  Each set via `_validate_svg_attribute`.
- Register tool, re-export.

### 5.3 REFACTOR
- Extract `_ensure_defs(root) -> Element`.
- Extract `_validate_color_hex(value: str)`.

### 5.4 Safety considerations
- Color regex prevents `url(...)`, `javascript:`, `expression(...)`.
- Numeric bounds prevent NaN/Inf and huge strings.
- Offset/opacity range-checked.
- Stop count bounded to prevent DoS.
- `_sanitize_tree` still runs on save (defense-in-depth).

---

## Phase 6: `duplicate_object`

### Model
```python
class DuplicateArgs(BaseModel):
    source: Selector        # CSS selector or #id
    new_id: str | None = None
    offset_dx: float = 0.0
    offset_dy: float = 0.0
    # If source matches multiple, tool duplicates only the first match
    # and returns its index; caller can iterate.
```

### 6.1 RED — `tests/test_dom_duplicate.py` **(new)**
- `test_duplicate_object_by_id` — input has `<rect id="r1">`, result
  contains two rects, second with new id.
- `test_duplicate_object_by_class_uses_first_match`.
- `test_duplicate_object_auto_id_when_absent`.
- `test_duplicate_object_explicit_new_id`.
- `test_duplicate_object_applies_transform_offset` — copy has
  `transform="translate(10, 5)"` (appended, not replacing existing).
- `test_duplicate_object_preserves_children` — a `<g>` with nested
  elements is deep-copied.
- `test_duplicate_object_not_found_returns_changed_zero`.
- `test_duplicate_object_rejects_unsafe_selector` — validated by
  `Selector` already, but assert MCP-level rejection in
  `test_security_boundaries.py`.
- `test_duplicate_object_rejects_dangerous_subtree` — input source
  contains a `<script>` child; after duplicate + save, neither original
  nor copy retains it (proves `_sanitize_tree` still wins).
- `test_duplicate_object_rejects_unsafe_new_id`.

### 6.2 GREEN
- Use `copy.deepcopy` on the matched element.
- Update `id` attribute on the copy (validate first).
- If offsets non-zero, append
  `f"translate({dx},{dy})"` to any existing `transform` attr.
- Insert after the original via `el.addnext(copy_el)`.

### 6.3 REFACTOR
- Extract `_append_transform(el, extra: str)` helper.

### 6.4 Safety considerations
- Deep-copied subtree is still subject to `_sanitize_tree` before save.
- New id validated.
- Selector already locked down by existing `Selector` model.
- No raw XML strings constructed.

---

## Phase 7: `query_dimensions`

Returns width/height and bbox for elements matching a selector. Read-only
tool: no `save_as`, no write.

### Model
```python
class QueryDimensionsArgs(BaseModel):
    doc: Doc
    selector: Selector
```

Return shape:
```python
{
  "ok": True,
  "matches": [
    {
      "id": "circle1",
      "tag": "circle",
      "x": 10.0, "y": 20.0,
      "width": 80.0, "height": 80.0,
      "bbox": {"x1": 10.0, "y1": 20.0, "x2": 90.0, "y2": 100.0}
    },
    ...
  ]
}
```

### 7.1 RED — `tests/test_dom_query_dimensions.py` **(new)**
- `test_query_dimensions_rect` — given a known `<rect x="5" y="10" width="20" height="30">`,
  assert bbox equals `(5, 10, 25, 40)`.
- `test_query_dimensions_circle` — `cx=50, cy=50, r=10` →
  `(40, 40, 60, 60)`.
- `test_query_dimensions_ellipse` — `cx, cy, rx, ry`.
- `test_query_dimensions_line` — `(x1,y1)` and `(x2,y2)` bounds (min/max).
- `test_query_dimensions_multiple_matches_returns_list_order`.
- `test_query_dimensions_no_match_returns_empty_list`.
- `test_query_dimensions_unsupported_element_skipped` — `<text>` without
  positional attrs returns `None` for width/height but still appears
  with `id`/`tag`.
- `test_query_dimensions_rejects_unsafe_selector`.
- `test_query_dimensions_does_not_write_any_file` — assert workspace
  contains no new files after call.

### 7.2 GREEN
- Prefer pure arithmetic on attributes (no Inkscape CLI call) for the
  five shape kinds. This keeps the tool fast and offline-testable.
- Helper `_bbox_of(el) -> dict | None` dispatches on localname.
- `_query_dimensions_impl` loads tree, calls `_select_nodes`, maps
  `_bbox_of`, returns list.

### 7.3 REFACTOR
- Split `_bbox_of` by tag to keep each branch < 10 lines.

### 7.4 Safety considerations
- Read-only: no `_ensure_in_workspace` save, no `_atomic_write`.
- Still runs `_load_svg_text` (so workspace + size limits apply).
- Selector validated as usual.

---

## Phase 8: `group_objects`

Wraps multiple matched elements in a new `<g>`.

### Model
```python
class GroupObjectsArgs(BaseModel):
    doc: Doc
    selectors: list[Selector]  # 1..32; union of matches is grouped
    group_id: str | None = None
    save_as: str
```

### 8.1 RED — `tests/test_dom_group.py` **(new)**
- `test_group_objects_wraps_matches_in_new_g` — output contains a `<g>`
  whose children are the previously-matched elements **in document
  order**, and the `<g>` is inserted at the original position of the
  first match.
- `test_group_objects_auto_id`.
- `test_group_objects_explicit_id`.
- `test_group_objects_preserves_sibling_order_outside_group`.
- `test_group_objects_no_match_returns_changed_zero_and_no_write` — do
  not create an empty `<g>`, do not write file.
- `test_group_objects_rejects_duplicate_id`.
- `test_group_objects_rejects_unsafe_id`.
- `test_group_objects_respects_selector_limit` — 33 selectors raises.
- `test_group_objects_rejects_grouping_root` — caller cannot pass a
  selector that would match the `<svg>` element itself.
- **Security boundary:** `test_group_objects_rejects_unsafe_selector`
  in `test_security_boundaries.py`.

### 8.2 GREEN
- Load tree. For each selector call `_select_nodes`, collect in a
  deduped ordered list (keep document order).
- If empty → `{"ok": True, "changed": 0, "out": None}`.
- Reject if any match is the root `svg` element.
- Create `<g id="...">`, insert at index of first match's parent, move
  matched nodes in via `g.append(node)` (lxml move semantics).
- Write tree.

### 8.3 REFACTOR
- Extract `_document_order_dedupe(nodes)` helper.
- Extract `_reject_root_match(root, nodes)` guard.

### 8.4 Safety considerations
- id validated.
- Upper bound on selector count (DoS).
- No raw XML constructed.
- Cannot group the root (prevents accidentally wrapping the entire
  document, which would change the SVG root type in some parsers).

---

## Ordering / Dependency Graph

```
Phase 0 (helpers + refactor)
   │
   ├──> Phase 1 create_shape ────────────────┐
   │                                          │
   ├──> Phase 2 create_layer ──> Phase 3 rename_layer
   │                        └──> Phase 4 set_layer_visibility
   │
   ├──> Phase 5 create_gradient ──> (optional follow-up:
   │        create_shape fill="url(#id)" tests)
   │
   ├──> Phase 6 duplicate_object   (depends only on Phase 0)
   │
   ├──> Phase 7 query_dimensions   (depends only on Phase 0)
   │
   └──> Phase 8 group_objects      (depends only on Phase 0)
```

Phases 3 and 4 must come after Phase 2 because their tests require
Inkscape layers in the input SVG and the Phase 2 fixtures produce them.
All other phases are independent and can be parallelized across
sub-branches if desired. **Phase 0 is blocking for all of them.**

## Combined Server Re-Export Checklist (do for every new tool)

1. Import the impl from `dom_server`.
2. Add a `@tool("<name>")` + `@flatten_pydantic_params` wrapper in
   `combined.py` that calls `dom_server._init_config(CFG)` then
   delegates to the impl.
3. Add one smoke test in `tests/test_combined_server_integration.py`
   calling the tool with flattened args (`doc_type`, `doc_svg`, etc.).
4. Add one security test in `tests/test_security_boundaries.py` for the
   tool's worst-case attack surface.

## Testing Strategy

- **Unit tests** (`tests/test_dom_helpers.py`): `_css_to_xpath`,
  `_validate_id`, `_validate_color_hex`, `_validate_numeric`, `_bbox_of`.
- **DOM integration tests** (`tests/test_dom_<tool>.py`): call the tool
  through `Client(dom_server.app)`, assert on result + file contents.
- **Combined integration tests**: thin smoke tests through
  `Client(combined.app)` to confirm flattening works for each tool.
- **Security boundary tests** (`tests/test_security_boundaries.py`): one
  test per tool covering the tool's most dangerous input (unsafe
  selector, unsafe id, unknown attr/style, path traversal on `save_as`,
  oversize inline svg).
- **Regression**: every phase runs the full existing suite before commit.

## Success Criteria

- [ ] All new tests pass (`pytest tests/`).
- [ ] Existing test suite still passes.
- [ ] Coverage for `dom_server.py` stays at or above current baseline.
- [ ] `ruff` / project linters clean.
- [ ] `_css_to_xpath` is the single source of truth for selector→xpath.
- [ ] No new tool constructs XML via string concatenation.
- [ ] No new tool bypasses `_validate_svg_attribute` or `_sanitize_tree`.
- [ ] Every new tool re-exported in `combined.py` and covered by a
      security-boundary test.

## Risks & Mitigations

- **Risk:** `_css_to_xpath` extraction accidentally changes existing
  `dom_set` behavior.
  **Mitigation:** unit tests in Phase 0.1 pin exact xpath strings for
  every currently-supported selector shape before touching production
  code.
- **Risk:** Inkscape namespace not declared on root when `create_layer`
  runs against a minimal SVG, causing downstream parsers to fail.
  **Mitigation:** `_ensure_inkscape_namespace` test asserts root nsmap.
- **Risk:** `duplicate_object` deep-copy includes a `<script>` that is
  then re-inserted.
  **Mitigation:** `_sanitize_tree` runs on every `_write_tree`; a test
  specifically exercises this path.
- **Risk:** `query_dimensions` arithmetic diverges from Inkscape's real
  bbox because the tool does not call Inkscape CLI.
  **Mitigation:** document the tool as "attribute-derived bbox, not
  render-aware"; add a note in the docstring.
- **Risk:** `flatten_pydantic_params` produces awkward flat names
  (e.g. `shape_attrs`) that are hard for MCP clients to pass.
  **Mitigation:** dict fields serialize to JSON strings via the existing
  flattener pattern used for `ops_json`; add a combined-server test per
  tool to confirm.

## Rollback Plan

- Every tool lands in its own small PR-sized commit sequence (red →
  green → refactor). To roll back a single tool: revert its three
  commits + the combined re-export + the test file.
- Phase 0 refactor is the only commit that touches existing code; if it
  needs to be reverted, the new tools come with it.
