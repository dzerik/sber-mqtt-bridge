"""Contract tests for the no-build SPA panel in ``custom_components/sber_mqtt_bridge/www``.

The panel has no JS test runner, so these tests guard the frontend from
the outside:

* **Parity** — ``www/utils.js`` mirrors ``name_utils.py``.  Both the raw
  regex source and (when ``node`` is available) the real JS function are
  compared against the Python source of truth.
* **Registry** — the category ``<select>`` must be fed from the backend,
  never from a hand-maintained copy that silently drifts from
  :data:`sber_entity_map.OVERRIDABLE_CATEGORIES`.
* **Live subscriptions** — DevTools components must re-subscribe after a
  detach/re-attach cycle instead of dying silently.
* **Accessibility** — clickable non-button elements must be reachable by
  keyboard.
* **Syntax** — every shipped module parses.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge.name_utils import (
    _SALUT_NAME,
    is_salut_friendly_name,
    slugify_sber_id,
)
from custom_components.sber_mqtt_bridge.sber_entity_map import OVERRIDABLE_CATEGORIES

WWW = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge" / "www"
COMPONENTS = WWW / "components"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _read(rel: str) -> str:
    """Return the source of a ``www``-relative JS module."""
    return (WWW / rel).read_text(encoding="utf-8")


def _js_modules() -> list[Path]:
    """Every first-party module shipped in ``www`` (vendored lit excluded)."""
    return sorted(p for p in WWW.rglob("*.js") if "vendor" not in p.parts)


# --------------------------------------------------------------------------- #
# Shared case matrix for the name validator
# --------------------------------------------------------------------------- #

# (name, expected) — ``expected`` is what BOTH implementations must return.
SALUT_NAME_CASES: list[tuple[str, bool]] = [
    # Sber's own documentation examples — the hyphen must pass.
    ("Смарт-телевизор", True),
    ("Люстра-1", True),
    ("-" * 3, True),
    # Plain Cyrillic.
    ("Свет", True),
    ("Лампа кухня", True),
    ("Ёжик", True),
    ("ёжик", True),
    ("ЁЛКА", True),
    ("приёмник", True),
    # Digits and spaces.
    ("123", True),
    ("   ", True),
    ("Розетка 2", True),
    # Length bounds: 3..33 inclusive.
    ("аб", False),
    ("абв", True),
    ("а" * 33, True),
    ("а" * 34, False),
    ("", False),
    # Alphabet bounds.
    ("Living Room", False),
    ("Лампа_кухня", False),
    ("Лампа!", False),
    ("Лампа.", False),
    ("Свет\n", False),
    ("Свет\nещё", False),
    ("Лампа 💡", False),
    ("Свет,кухня", False),
]

SLUGIFY_CASES: list[str] = [
    "",
    "Смарт-телевизор",
    "Удлинитель Кухня №1",
    "Living Room Lamp",
    "   spaces   ",
    "a!!b??c",
    "Ёжик",
    "Люстра-1",
]


# --------------------------------------------------------------------------- #
# utils.js  <->  name_utils.py parity
# --------------------------------------------------------------------------- #


class TestSalutNameParity:
    """``isValidSalutName`` must accept exactly what Python accepts."""

    @staticmethod
    def _js_pattern() -> str:
        """Extract ``SALUT_NAME_RE`` from ``utils.js`` as a Python pattern.

        Only ``\\uXXXX`` escapes are decoded — everything else (notably
        ``\\-``) carries the same meaning in both regex dialects.
        """
        src = _read("utils.js")
        match = re.search(r"^export const SALUT_NAME_RE = /(.+)/;$", src, re.MULTILINE)
        assert match, "utils.js must export a top-level SALUT_NAME_RE regex literal"
        return re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda m: chr(int(m.group(1), 16)),
            match.group(1),
        )

    def test_python_matrix_is_self_consistent(self):
        """Guards the matrix itself: it must describe the Python source of truth."""
        for name, expected in SALUT_NAME_CASES:
            assert is_salut_friendly_name(name) is expected, name

    def test_js_regex_source_matches_python(self):
        """The JS literal, decoded, must behave like ``_SALUT_NAME``.

        Runs without node so the parity guard is never silently skipped.
        """
        js_re = re.compile(self._js_pattern())
        for name, expected in SALUT_NAME_CASES:
            assert bool(js_re.fullmatch(name)) is expected, f"{name!r} (js regex)"
            assert bool(js_re.fullmatch(name)) is bool(_SALUT_NAME.fullmatch(name)), name

    @requires_node
    def test_real_js_function_matches_python(self, tmp_path):
        """Execute the shipped ``isValidSalutName`` in node and compare."""
        results = _run_js_helpers(tmp_path, [name for name, _ in SALUT_NAME_CASES])
        for (name, expected), (js_valid, _slug) in zip(SALUT_NAME_CASES, results, strict=True):
            assert js_valid is expected, f"{name!r}: JS said {js_valid}, Python says {expected}"


class TestSlugifyParity:
    """``slugify`` must produce the same ids as ``slugify_sber_id``."""

    @requires_node
    def test_real_js_slugify_matches_python(self, tmp_path):
        results = _run_js_helpers(tmp_path, SLUGIFY_CASES)
        for source, (_valid, js_slug) in zip(SLUGIFY_CASES, results, strict=True):
            assert js_slug == slugify_sber_id(source), f"{source!r}"


def _run_js_helpers(tmp_path: Path, cases: list[str]) -> list[list]:
    """Run ``utils.js`` helpers in node over ``cases``.

    Returns:
        One ``[isValidSalutName, slugify]`` pair per input, in order.
    """
    # Copied with an .mjs extension so node parses it as an ES module.
    (tmp_path / "utils.mjs").write_text(_read("utils.js"), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        'import { isValidSalutName, slugify } from "./utils.mjs";\n'
        "const cases = JSON.parse(process.argv[2]);\n"
        "console.log(JSON.stringify(cases.map((c) => [isValidSalutName(c), slugify(c)])));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(  # noqa: S603
        [NODE, str(driver), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
# Category registry must come from the backend
# --------------------------------------------------------------------------- #


class TestCategoryRegistry:
    """The override ``<select>`` must not carry a hand-maintained category list."""

    def test_entity_row_has_no_hardcoded_category_array(self):
        src = _read("components/sber-entity-row.js")
        # Ignore prose: only executable lines may not enumerate categories.
        code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith(("*", "//", "/*")))
        quoted = set(re.findall(r'"([a-z0-9_]+)"', code))
        hardcoded = quoted & set(OVERRIDABLE_CATEGORIES)
        assert not hardcoded, (
            f"sber-entity-row.js hardcodes Sber categories {sorted(hardcoded)} — feed them from list_categories instead"
        )

    def test_entity_row_renders_categories_from_property(self):
        src = _read("components/sber-entity-row.js")
        assert "categories: { type: Array }" in src
        assert "this._categoryOptions().map(" in src

    def test_device_table_fetches_categories_over_websocket(self):
        src = _read("components/sber-device-table.js")
        assert 'type: "sber_mqtt_bridge/list_categories"' in src, (
            "sber-device-table must source the category registry from the backend"
        )
        assert ".categories=${this._categories}" in src, "the fetched registry must be handed down to sber-entity-row"

    def test_list_categories_endpoint_exists(self):
        """The WS command the table depends on must actually be registered."""
        api = (WWW.parent / "websocket_api" / "devices_grouped.py").read_text(encoding="utf-8")
        assert '"sber_mqtt_bridge/list_categories"' in api


# --------------------------------------------------------------------------- #
# Live WS subscriptions survive detach / re-attach
# --------------------------------------------------------------------------- #

SUBSCRIBING_COMPONENTS = [
    ("sber-devtools.js", "_subscribeMessages", "_unsubscribeMessages"),
    ("sber-traces.js", "_subscribe", "_unsubscribe"),
    ("sber-state-diff.js", "_subscribe", "_unsubscribe"),
    ("sber-replay.js", "_subscribe", "_unsubscribe"),
    ("sber-validation.js", "_subscribe", "_unsubscribe"),
]


class TestSubscriptionLifecycle:
    """Every subscribing component must re-subscribe when re-attached."""

    @pytest.mark.parametrize(("name", "sub", "unsub"), SUBSCRIBING_COMPONENTS)
    def test_subscribes_from_connected_callback(self, name, sub, unsub):
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        connected = _method_body(src, "connectedCallback")
        assert connected is not None, f"{name} must define connectedCallback"
        assert f"this.{sub}()" in connected, (
            f"{name}: connectedCallback must re-subscribe — otherwise the live feed "
            "dies after HA navigates away from the panel and back"
        )
        disconnected = _method_body(src, "disconnectedCallback")
        assert disconnected is not None, f"{name} must define disconnectedCallback"
        assert f"this.{unsub}()" in disconnected

    @pytest.mark.parametrize(("name", "sub", "unsub"), SUBSCRIBING_COMPONENTS)
    def test_no_one_shot_hass_guard(self, name, sub, unsub):
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        assert "_hassReady" not in src, f"{name}: the one-shot _hassReady guard permanently blocks re-subscription"

    @pytest.mark.parametrize(("name", "sub", "unsub"), SUBSCRIBING_COMPONENTS)
    def test_subscribe_is_reentrancy_safe(self, name, sub, unsub):
        """``updated()`` fires on every hass mutation — one subscription only."""
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        body = _method_body(src, sub)
        assert body is not None
        assert "this._subscribing" in body, f"{name}: {sub} must guard against concurrent in-flight subscribes"
        assert "if (!this.isConnected)" in body, (
            f"{name}: {sub} must drop the subscription if the element detached while the round-trip was in flight"
        )

    @pytest.mark.parametrize(("name", "sub", "unsub"), SUBSCRIBING_COMPONENTS)
    def test_live_buffer_is_capped(self, name, sub, unsub):
        """Unbounded live buffers grow forever on a long-open DevTools tab."""
        body = _method_body((COMPONENTS / name).read_text(encoding="utf-8"), sub)
        assert body is not None
        assert ".slice(-MAX_" in body, f"{name}: live appends must be capped"


def _method_body(src: str, name: str) -> str | None:
    """Return the brace-balanced body of a class method, or ``None``."""
    match = re.search(rf"^  (?:async )?{re.escape(name)}\([^)]*\) \{{$", src, re.MULTILINE)
    if match is None:
        return None
    depth = 0
    start = src.index("{", match.start())
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return None


# Native elements already handle Enter/Space; ``.overlay`` is a backdrop whose
# keyboard equivalent is the dialog's Escape handler.
_NATIVE_INTERACTIVE = {"button", "input", "a", "select", "textarea", "label", "option"}
_BACKDROP_CLASS = 'class="overlay"'
# A dialog container's @click only stops backdrop propagation — it is not a
# control, so it needs no keyboard activation of its own.
_NON_ACTIVATING = 'role="dialog"'


def _relative_js_modules() -> list[str]:
    """``www``-relative paths of every first-party module."""
    return [p.relative_to(WWW).as_posix() for p in _js_modules()]


def _clickable_without_keyboard(src: str) -> list[str]:
    """Return tag names of ``@click`` elements with no keyboard equivalent.

    The element "window" runs from its opening ``<`` to the start of the
    next tag, which is where lit templates put sibling event bindings.
    """
    offenders: list[str] = []
    for match in re.finditer(r"@click=", src):
        open_pos = src.rfind("<", 0, match.start())
        if open_pos == -1:
            continue
        tag_match = re.match(r"<([a-zA-Z][\w-]*)", src[open_pos:])
        if tag_match is None:
            continue
        tag = tag_match.group(1).lower()
        if tag in _NATIVE_INTERACTIVE:
            continue
        next_tag = src.find("<", open_pos + 1)
        window = src[open_pos : next_tag if next_tag != -1 else len(src)]
        if any(token in window for token in ("@keydown=", _BACKDROP_CLASS, _NON_ACTIVATING)):
            continue
        offenders.append(tag)
    return offenders


# --------------------------------------------------------------------------- #
# Baseline keyboard accessibility
# --------------------------------------------------------------------------- #


class TestAccessibility:
    """Interactive non-button elements must be operable without a mouse."""

    def test_panel_tabs_are_a_tablist(self):
        src = _read("sber-panel.js")
        assert 'role="tablist"' in src
        assert 'role="tab"' in src
        assert "aria-selected=" in src
        assert "_onTabKeydown" in src, "tabs must respond to arrow/Enter keys"
        assert 'role="tabpanel"' in src

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_clickable_elements_have_keyboard_handlers(self, path):
        """Every ``@click`` on a non-native element needs a ``@keydown`` sibling."""
        offenders = _clickable_without_keyboard(_read(path))
        assert not offenders, (
            f"{path}: clickable <{'>, <'.join(offenders)}> element(s) are mouse-only — add role/tabindex/@keydown"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "components/sber-wizard.js",
            "components/sber-link-dialog.js",
            "components/sber-detail-dialog.js",
        ],
    )
    def test_dialogs_are_modal_and_escapable(self, path):
        src = _read(path)
        assert 'role="dialog"' in src, f"{path}: dialog container needs role=dialog"
        assert 'aria-modal="true"' in src
        assert 'e.key === "Escape"' in src, f"{path}: Escape must close the dialog"
        assert "_returnFocusTo" in src, f"{path}: focus must return to the opener"

    def test_toast_is_announced(self):
        src = _read("components/sber-toast.js")
        assert "aria-live=" in src
        assert "role=" in src

    @pytest.mark.parametrize("path", ["sber-panel.js", "components/sber-entity-row.js"])
    def test_focus_is_visible(self, path):
        assert ":focus-visible" in _read(path), f"{path}: keyboard focus must be visible"

    def test_icon_only_buttons_are_labelled(self):
        """Emoji-only action buttons carry no accessible name without aria-label."""
        src = _read("components/sber-entity-row.js")
        icon_buttons = re.findall(r'<button class="icon-btn[^>]*>', src)
        assert icon_buttons, "expected icon-only action buttons in the row"
        for button in icon_buttons:
            assert "aria-label=" in button, button


# --------------------------------------------------------------------------- #
# Syntax
# --------------------------------------------------------------------------- #


class TestModulesParse:
    @requires_node
    def test_every_module_parses(self, tmp_path):
        """Parse every shipped module with node.

        Each file is copied to ``.mjs`` first: ``node --check`` on a ``.js``
        file containing ESM syntax exits 0 even when the source is broken
        (CommonJS parse fails, module-detection fallback swallows the error).
        """
        bad = []
        for path in _js_modules():
            probe = tmp_path / f"{path.stem}.mjs"
            probe.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(  # noqa: S603
                [NODE, "--check", str(probe)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                bad.append(f"{path.name}: {proc.stderr.strip().splitlines()[:3]}")
        assert not bad, "\n".join(bad)

    def test_panel_imports_every_component_it_renders(self):
        """A component rendered by the panel but never imported never upgrades."""
        panel = _read("sber-panel.js")
        imported = set(re.findall(r"import\(`\./components/([a-z-]+)\.js", panel))
        rendered = set(re.findall(r"<(sber-[a-z-]+)\b", panel))
        # sber-entity-row / sber-detail-dialog are imported by sber-device-table.
        missing = {tag for tag in rendered if tag not in imported}
        assert not missing, f"rendered but not imported by sber-panel.js: {sorted(missing)}"
