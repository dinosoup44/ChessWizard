"""Trusted template providers and registry. No file import or executable packs."""
import json
import re
from string import Formatter
from typing import Protocol
from .templates import DEFAULT_PACK, COMMON


class TemplateProvider(Protocol):
    pack_id: str
    def render(self, key: str, **values: str) -> str: ...
    def label(self, category: str, code: str) -> str: ...
    def style(self, name: str) -> dict: ...


def _fields(template):
    fields = set()
    for _, name, spec, conversion in Formatter().parse(template):
        if name is not None:
            if not re.fullmatch(r"[a-z_]+", name) or spec or conversion:
                raise ValueError("Only simple named placeholders are allowed")
            fields.add(name)
    return fields


class DataTemplateProvider:
    """Application-supplied JSON-shaped data, copied and validated on construction.

    This is not an untrusted community loader. Data-only does not establish that
    arbitrary wording is factually faithful; community approval remains future work.
    """
    def __init__(self, document):
        data = json.loads(json.dumps(document, allow_nan=False))
        expected = {"schema_version", "pack_id", "name", "templates", "styles", "outcome_labels", "motif_labels", "tactic_labels"}
        if set(data) != expected or type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported feedback pack structure")
        if not isinstance(data["pack_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", data["pack_id"]):
            raise ValueError("Invalid pack ID")
        if not isinstance(data["name"], str) or not data["name"]:
            raise ValueError("Missing pack name")
        if not isinstance(data["templates"], dict) or set(data["templates"]) != set(COMMON):
            raise ValueError("Templates must implement the V1 wording contract")
        for key, template in data["templates"].items():
            if not isinstance(template, str) or len(template) > 4000 or _fields(template) != _fields(COMMON[key]):
                raise ValueError(f"Invalid placeholders for {key}")
        for category in ("outcome_labels", "motif_labels", "tactic_labels"):
            if not isinstance(data[category], dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 200 or '{' in v or '}' in v for k, v in data[category].items()):
                raise ValueError("Labels must be plain text")
        if not isinstance(data["styles"], dict) or not data["styles"]:
            raise ValueError("At least one style is required")
        for style in data["styles"].values():
            if not isinstance(style, dict) or set(style) != {"summary_template", "detail_level", "include_evidence", "include_teaching_note"}:
                raise ValueError("Invalid style fields")
            if style["summary_template"] not in {"explanation", "alert", "summary"} or not isinstance(style["detail_level"], str):
                raise ValueError("Invalid style presentation")
            if any(type(style[k]) is not bool for k in ("include_evidence", "include_teaching_note")):
                raise ValueError("Style switches must be booleans")
        self._data = data
        self.pack_id = data["pack_id"]

    def render(self, key, **values):
        return self._data["templates"][key].format_map(values)

    def label(self, category, code):
        return self._data[category].get(code, code.removeprefix("missed_").replace("_", " ").capitalize())

    def style(self, name):
        if name not in self._data["styles"]:
            raise ValueError(f"Unknown feedback style: {name}")
        return dict(self._data["styles"][name])


class FeedbackRegistry:
    def __init__(self):
        self._providers = {}

    def register(self, provider: TemplateProvider):
        if provider.pack_id in self._providers:
            raise ValueError(f"Duplicate feedback provider: {provider.pack_id}")
        self._providers[provider.pack_id] = provider

    def get(self, pack_id):
        if pack_id not in self._providers:
            raise ValueError(f"Unknown feedback provider: {pack_id}")
        return self._providers[pack_id]


def default_registry():
    registry = FeedbackRegistry()
    registry.register(DataTemplateProvider(DEFAULT_PACK))
    return registry
