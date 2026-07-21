"""Unit tests for dom_server helper functions (_css_to_xpath, _validate_id).

These tests are written RED-first: the functions do not exist yet at time of
writing, so imports will fail with ImportError / AttributeError until they are
extracted / added in Part 0.3.
"""

import pytest

from inkscape_mcp.dom_server import _css_to_xpath, _validate_id


class TestCssToXpath:
    def test_simple_element(self):
        assert _css_to_xpath("circle") == "//svg:circle"

    def test_id_selector(self):
        assert _css_to_xpath("#circle1") == "//*[@id='circle1']"

    def test_class_selector(self):
        result = _css_to_xpath(".shape")
        assert "contains" in result and "shape" in result

    def test_element_class(self):
        result = _css_to_xpath("rect.shape")
        assert "svg:rect" in result

    def test_wildcard(self):
        assert _css_to_xpath("*") == "//*"

    def test_unsupported_returns_nomatch(self):
        assert _css_to_xpath("circle > rect") == "//NOMATCH"

    def test_comma_list_of_tags(self):
        assert _css_to_xpath("rect, circle") == "//svg:rect | //svg:circle"

    def test_comma_list_mixes_ids_and_classes(self):
        # Each comma part gets the full grammar, not just bare tag names.
        result = _css_to_xpath("rect, #my-id, .cls")
        parts = result.split(" | ")
        assert parts[0] == "//svg:rect"
        assert parts[1] == "//*[@id='my-id']"
        assert "contains" in parts[2] and "cls" in parts[2]
        assert "//NOMATCH" not in result


class TestValidateId:
    def test_accepts_safe(self):
        for v in ["myId", "layer-1", "_under"]:
            _validate_id(v)  # no exception

    def test_rejects_empty(self):
        with pytest.raises(Exception):
            _validate_id("")

    def test_rejects_starts_with_digit(self):
        with pytest.raises(Exception):
            _validate_id("1bad")

    def test_rejects_spaces(self):
        with pytest.raises(Exception):
            _validate_id("x y")

    def test_rejects_too_long(self):
        with pytest.raises(Exception):
            _validate_id("a" * 100)

    def test_rejects_script_tag(self):
        with pytest.raises(Exception):
            _validate_id("<script>")
