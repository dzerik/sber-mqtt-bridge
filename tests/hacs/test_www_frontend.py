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
  detach/re-attach cycle instead of dying silently, and the broadcast
  message feed must be multiplexed through a single WS subscription.
* **Advisory validation** — the wizard may warn about a name, never refuse
  one the backend would publish (``name_utils`` only logs).
* **Partial batches** — a half-failed multi-add reports per-entity outcomes
  and retries only what failed.
* **Synchronisation** — mutations are confirmed by polling the backend, not
  by sleeping a fixed 1.5 s and hoping.
* **Accessibility** — clickable non-button elements must be reachable by
  keyboard; no native ``confirm()``/``alert()``.
* **Syntax** — every shipped module parses.

Several checks execute the shipped code in node — either the whole module
(``utils.js``, ``message-bus.js``, ``lit-base.js`` are dependency-free) or a
single method lifted out of a LitElement class — so they assert behaviour
rather than a paraphrase of it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge.devices.light import LightEntity
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


def _strip_comments(src: str) -> str:
    """Drop ``/* */`` and ``//`` comments so prose is not mistaken for code."""
    without_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return "\n".join(re.sub(r"(?<![:\w])//.*$", "", line) for line in without_block.splitlines())


def _strip_media_blocks(src: str) -> str:
    """Remove ``@media`` blocks — responsive overrides are not duplicates."""
    out: list[str] = []
    index = 0
    while True:
        start = src.find("@media", index)
        if start == -1:
            out.append(src[index:])
            return "".join(out)
        out.append(src[index:start])
        depth = 0
        cursor = src.index("{", start)
        for i in range(cursor, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    index = i + 1
                    break
        else:  # pragma: no cover - unbalanced source would fail the parse test
            return "".join(out)


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

# Components that own their WS subscription directly.  DevTools and Replay
# share one through ``message-bus.js``, which carries the guards instead.
OWN_SUBSCRIPTION_COMPONENTS = [
    ("sber-traces.js", "_subscribe"),
    ("sber-state-diff.js", "_subscribe"),
    ("sber-validation.js", "_subscribe"),
]

BUS_CONSUMERS = ["sber-devtools.js", "sber-replay.js"]


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

    @pytest.mark.parametrize(("name", "sub"), OWN_SUBSCRIPTION_COMPONENTS)
    def test_subscribe_is_reentrancy_safe(self, name, sub):
        """``updated()`` fires on every hass mutation — one subscription only."""
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        body = _method_body(src, sub)
        assert body is not None
        assert "this._subscribing" in body, f"{name}: {sub} must guard against concurrent in-flight subscribes"
        assert "if (!this.isConnected)" in body, (
            f"{name}: {sub} must drop the subscription if the element detached while the round-trip was in flight"
        )

    @pytest.mark.parametrize(("name", "sub"), OWN_SUBSCRIPTION_COMPONENTS)
    def test_live_buffer_is_capped(self, name, sub):
        """Unbounded live buffers grow forever on a long-open DevTools tab."""
        body = _method_body((COMPONENTS / name).read_text(encoding="utf-8"), sub)
        assert body is not None
        assert ".slice(-MAX_" in body, f"{name}: live appends must be capped"


def _method_span(src: str, name: str) -> tuple[int, int, int] | None:
    """Locate a class method or getter.

    Returns:
        ``(signature_start, body_open_brace, body_end)`` or ``None``.
        The opening brace is taken from the end of the signature line, so
        destructured parameters (``{ timeout = ... } = {}``) do not throw
        the brace counter off.
    """
    match = re.search(
        rf"^  (?:async |get )?{re.escape(name)}\(.*\) \{{$",
        src,
        re.MULTILINE,
    )
    if match is None:
        return None
    depth = 0
    start = match.end() - 1
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), start, i + 1
    return None


def _method_body(src: str, name: str) -> str | None:
    """Return the brace-balanced body of a class method, or ``None``."""
    span = _method_span(src, name)
    if span is None:
        return None
    return src[span[1] : span[2]]


def _method_source(src: str, name: str) -> str:
    """Return a method verbatim (signature + body), ready to paste into a literal.

    Used to execute a shipped method in node without instantiating the
    whole LitElement — the test then checks real behaviour, not a
    paraphrase of it.
    """
    span = _method_span(src, name)
    assert span is not None, f"method {name} not found"
    return src[span[0] : span[2]].strip()


# Native elements already handle Enter/Space; ``.overlay`` is a backdrop whose
# keyboard equivalent is the dialog's Escape handler.
_NATIVE_INTERACTIVE = {"button", "input", "a", "select", "textarea", "label", "option"}
_BACKDROP_CLASS = 'class="overlay"'
# A dialog container's @click only stops backdrop propagation — it is not a
# control, so it needs no keyboard activation of its own.
_NON_ACTIVATING = 'role="dialog"'


def _exported_names(src: str) -> set[str]:
    """Return the names a ``www`` module exports (declarations + destructures)."""
    exported: set[str] = set()
    for match in re.finditer(
        r"^export (?:async )?(?:function|const|class)\s+([A-Za-z_$][\w$]*)",
        src,
        re.MULTILINE,
    ):
        exported.add(match.group(1))
    for match in re.finditer(r"^export const \{([^}]+)\} =", src, re.MULTILINE):
        exported.update(name.strip() for name in match.group(1).split(",") if name.strip())
    return exported


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


# Every element the panel must have registered by the time it is loaded.
EXPECTED_ELEMENTS = {
    "sber-detail-dialog",
    "sber-json-block",
    "sber-device-table",
    "sber-devtools",
    "sber-diagnose",
    "sber-entity-row",
    "sber-link-dialog",
    "sber-mqtt-panel",
    "sber-replay",
    "sber-settings",
    "sber-state-diff",
    "sber-stats-grid",
    "sber-status-card",
    "sber-toast",
    "sber-toolbar",
    "sber-traces",
    "sber-validation",
    "sber-wizard",
}

# Enough of a DOM for lit and the components to evaluate.  Not a rendering
# environment — just enough that every module body actually runs.
_DOM_SHIM = """
globalThis.HTMLElement = class {
  attachShadow() {
    return { activeElement: null, querySelector: () => null, querySelectorAll: () => [] };
  }
};
globalThis.Document = class {};
globalThis.Node = class {};
globalThis.Element = class {};
globalThis.DocumentFragment = class {};
globalThis.ShadowRoot = class {};
globalThis.CSSStyleSheet = class { replaceSync() {} };
globalThis.customElements = {
  /* The browser reads observedAttributes while defining, which makes lit
   * finalize the class and evaluate its static styles.  Do the same, or a
   * broken css`` template only shows up in the user's console. */
  define: (name, ctor) => {
    (globalThis.__defined ||= []).push(name);
    try {
      void ctor.observedAttributes;
      void ctor.elementStyles;
    } catch (e) {
      (globalThis.__defineErrors ||= []).push(`${name}: ${e && e.message}`);
    }
  },
  get: () => undefined,
};
globalThis.document = {
  activeElement: null,
  adoptedStyleSheets: [],
  createElement: () => ({ style: {}, setAttribute() {}, appendChild() {}, content: {}, innerHTML: "" }),
  createTreeWalker: () => ({}),
  createComment: () => ({}),
  createTextNode: () => ({}),
  addEventListener() {},
  removeEventListener() {},
  head: { appendChild() {} },
  body: { appendChild() {}, removeChild() {} },
};
globalThis.window = globalThis;
globalThis.getComputedStyle = () => ({});
"""


class TestModuleGraphLinks:
    """The shipped modules must actually link and register their elements.

    ``node --check`` only parses.  This evaluates the whole graph the way
    the browser does — through ``sber-panel.js`` with a ``?v=`` query — so a
    named import that no longer exists, a circular dependency or a module
    that throws on load fails here instead of in the user's browser
    console.
    """

    @requires_node
    def test_loading_the_panel_registers_every_component(self, tmp_path):
        driver = (
            _DOM_SHIM + "const out = { failures: [] };\n"
            f"const entry = {json.dumps((WWW / 'sber-panel.js').as_posix())};\n"
            'try { await import(entry + "?v=1.2.3"); }\n'
            "catch (e) { out.failures.push(String(e && e.message)); }\n"
            "out.defined = (globalThis.__defined || []).sort();\n"
            "out.defineErrors = globalThis.__defineErrors || [];\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["failures"] == [], f"the panel's import graph does not link: {out['failures']}"
        assert out["defineErrors"] == [], (
            "an element throws while the browser finalizes it — a stylesheet or "
            f"static property that only parses, never runs: {out['defineErrors']}"
        )
        assert set(out["defined"]) == EXPECTED_ELEMENTS, (
            f"registered {sorted(set(out['defined']) ^ EXPECTED_ELEMENTS)} unexpectedly"
        )
        assert len(out["defined"]) == len(set(out["defined"])), (
            f"an element was defined twice — a duplicated module instance: {out['defined']}"
        )

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_every_destructured_import_name_exists(self, path):
        """``const { x } = await import(...)`` yields ``undefined`` for a typo.

        Unlike a static ``import { x } from``, destructuring a dynamic import
        never fails at link time — the name is simply ``undefined`` and the
        component dies later somewhere unrelated.  Check the target's
        exports here instead.
        """
        src = _read(path)
        base = (WWW / path).parent
        imports = re.findall(r"const \{([^}]+)\} = await import\(`([^`$]+)\$\{_q\}`\)", src)
        for names, spec in imports:
            target = (base / spec).resolve()
            assert target.is_file(), f"{path}: imports {spec}, which does not exist"
            exported = _exported_names(target.read_text(encoding="utf-8"))
            wanted = {name.strip() for name in names.split(",") if name.strip()}
            missing = sorted(wanted - exported)
            assert not missing, (
                f"{path}: {spec} does not export {missing} — the dynamic import "
                f"silently binds them to undefined (exports: {sorted(exported)})"
            )


# --------------------------------------------------------------------------- #
# Salut name gate is advisory, not blocking
# --------------------------------------------------------------------------- #


def _run_node(tmp_path: Path, driver: str, *, extra_files: dict[str, str] | None = None) -> object:
    """Write ``driver.mjs`` (plus helpers) into ``tmp_path`` and run it.

    Returns:
        The JSON printed by the driver on stdout.
    """
    for name, content in (extra_files or {}).items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (tmp_path / "driver.mjs").write_text(driver, encoding="utf-8")
    proc = subprocess.run(  # noqa: S603
        [NODE, str(tmp_path / "driver.mjs")],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(proc.stdout)


# (name, expected advice level) — "" means "no remark at all".
NAME_ADVICE_CASES: list[tuple[str, str]] = [
    ("Лампа кухня", ""),
    ("Смарт-телевизор", ""),
    # Latin names are what the wizard used to refuse outright.
    ("Living Room Lamp", "info"),
    ("Lamp", "info"),
    # Too short for Salut, still perfectly publishable.
    ("Лк", "info"),
    ("", "warn"),
    ("а" * 64, "warn"),
]


class TestNameGateIsAdvisory:
    """The wizard must not refuse names the backend would happily publish.

    ``name_utils.warn_if_suspicious_name`` only logs, so a hard UI gate
    diverges from the actual contract.
    """

    @requires_node
    def test_name_advice_levels(self, tmp_path):
        """Execute the shipped ``_nameAdvice`` and check its verdicts."""
        method = _method_source(_read("components/sber-wizard.js"), "_nameAdvice")
        driver = (
            'import { isValidSalutName } from "./utils.mjs";\n'
            f"const wizard = {{ {method} }};\n"
            f"const cases = {json.dumps([name for name, _ in NAME_ADVICE_CASES])};\n"
            "console.log(JSON.stringify(cases.map((c) => wizard._nameAdvice(c))));\n"
        )
        results = _run_node(tmp_path, driver, extra_files={"utils.mjs": _read("utils.js")})
        for (name, expected), advice in zip(NAME_ADVICE_CASES, results, strict=True):
            assert advice["level"] == expected, f"{name!r}: got {advice}"
            if expected:
                assert advice["text"], f"{name!r}: an advisory level needs an explanation"

    @requires_node
    def test_advice_never_reports_a_blocking_level(self, tmp_path):
        """Only "" / "info" / "warn" exist — no level the footer could gate on."""
        method = _method_source(_read("components/sber-wizard.js"), "_nameAdvice")
        driver = (
            'import { isValidSalutName } from "./utils.mjs";\n'
            f"const wizard = {{ {method} }};\n"
            "const probes = ['', 'x', 'Лампа', 'Living Room', 'a'.repeat(200), '💡'];\n"
            "console.log(JSON.stringify(probes.map((p) => wizard._nameAdvice(p).level)));\n"
        )
        levels = _run_node(tmp_path, driver, extra_files={"utils.mjs": _read("utils.js")})
        assert set(levels) <= {"", "info", "warn"}, levels

    def test_finish_button_is_not_gated_by_name_validity(self):
        """``canFinish`` must not consult the Salut validator."""
        footer = _method_body(_read("components/sber-wizard.js"), "_renderFooter")
        assert footer is not None
        assert "isValidSalutName" not in footer, (
            "_renderFooter gates Finish on the Salut pattern again — the backend "
            "publishes Latin names, so the wizard must only advise"
        )
        assert "canFinish" in footer
        assert "this._loading" in footer, "Finish must still be disabled while a submit is in flight"

    def test_submit_does_not_bail_out_on_a_non_salut_name(self):
        """``_finish`` must not return early because of the name pattern."""
        body = _method_body(_read("components/sber-wizard.js"), "_finish")
        assert body is not None
        assert "isValidSalutName" not in body, (
            "_finish refuses to send non-Salut names again — that contradicts "
            "name_utils.warn_if_suspicious_name, which only logs"
        )

    def test_name_field_is_not_marked_invalid(self):
        """``aria-invalid``/``.invalid`` would announce an error that isn't one."""
        src = _read("components/sber-wizard.js")
        form = _method_body(src, "_renderPrimaryForm")
        assert form is not None
        assert "aria-invalid" not in form, "an advisory remark must not be announced as an error"
        assert "_nameAdvice" in form, "the form must render the advisory hint"


# --------------------------------------------------------------------------- #
# Multi-add: partial success is reported, never silently retried
# --------------------------------------------------------------------------- #


def _methods_as_object_body(src: str, names: list[str]) -> str:
    """Splice shipped class methods into an object-literal body.

    Getters, ``async`` methods and plain methods all keep their original
    syntax inside an object literal, so the executed code is byte-for-byte
    what ships — no paraphrase, no re-implementation.
    """
    return ",\n".join(_method_source(src, name) for name in names) + ","


_WIZARD_METHODS = ["_pendingPrimaries", "_finish", "_emitComplete"]

# A fake wizard carrying the real _finish/_emitComplete/_pendingPrimaries.
# ``shouldFail(msg)`` returns an error string to reject that call, or null.
_WIZARD_HARNESS = """
function makeWizard(shouldFail) {
  const wizard = {
    calls: [],
    events: [],
    hidden: false,
    _devices: [{ device_id: "dev1", primary: { entity_id: "switch.a" } }],
    _selectedDeviceId: "dev1",
    _selectedCategory: "socket",
    _selectedPrimaries: ["switch.a", "switch.b", "switch.c"],
    _perPrimary: {
      "switch.a": { name: "A", room: "Kitchen" },
      "switch.b": { name: "B", room: "Kitchen" },
      "switch.c": { name: "C", room: "Hall" },
    },
    _enabledLinks: new Set(["sensor.batt"]),
    _added: new Set(),
    _failed: [],
    _linksAttached: false,
    _loading: false,
    _error: "",
    hass: {
      callWS: async (msg) => {
        wizard.calls.push(msg);
        const reason = shouldFail(msg);
        if (reason) throw new Error(reason);
        return {};
      },
    },
    hide() { wizard.hidden = true; },
    dispatchEvent(event) { wizard.events.push(event.detail); },
    __METHODS__
  };
  return wizard;
}

function snapshot(wizard) {
  return {
    sent: wizard.calls.map((c) => c.primary_entity_id),
    links: wizard.calls.map((c) => c.linked_entity_ids),
    names: wizard.calls.map((c) => c.name),
    rooms: wizard.calls.map((c) => c.room),
    added: [...wizard._added],
    failed: wizard._failed,
    hidden: wizard.hidden,
    error: wizard._error,
    loading: wizard._loading,
    /* Copy: the caller resets wizard.events between rounds. */
    events: [...wizard.events],
  };
}
"""


def _run_wizard_scenario(tmp_path: Path, body: str) -> dict:
    """Execute ``body`` against the shipped wizard batch methods in node."""
    harness = _WIZARD_HARNESS.replace(
        "__METHODS__",
        _methods_as_object_body(_read("components/sber-wizard.js"), _WIZARD_METHODS),
    )
    return _run_node(tmp_path, harness + body)


class TestMultiAddPartialSuccess:
    """A half-failed batch must not re-register the entities that succeeded."""

    @requires_node
    def test_partial_batch_retries_only_the_failures(self, tmp_path):
        """Run the real ``_finish`` twice over a batch whose middle call fails.

        Guards the whole contract behaviourally: which ids go out on the
        retry, which carry ``linked_entity_ids``, what lands in ``_added``
        and what the ``wizard-complete`` detail actually contains.
        """
        out = _run_wizard_scenario(
            tmp_path,
            'let failing = new Set(["switch.b"]);\n'
            "const wizard = makeWizard((msg) =>"
            ' failing.has(msg.primary_entity_id) ? "backend said no" : null);\n'
            "const out = {};\n"
            "await wizard._finish();\n"
            "out.round1 = snapshot(wizard);\n"
            "const addedRef = wizard._added;\n"
            "wizard.calls.length = 0; wizard.events.length = 0;\n"
            "failing = new Set();\n"
            "await wizard._finish();\n"
            "out.round2 = snapshot(wizard);\n"
            "out.addedSetReplaced = addedRef !== wizard._added;\n"
            "wizard.calls.length = 0; wizard.events.length = 0;\n"
            "await wizard._finish();\n"
            "out.round3 = snapshot(wizard);\n"
            "console.log(JSON.stringify(out));\n",
        )

        first = out["round1"]
        assert first["sent"] == ["switch.a", "switch.b", "switch.c"], "the first submit must try every primary"
        assert first["names"] == ["A", "B", "C"], "each primary carries its own form values"
        assert first["rooms"] == ["Kitchen", "Kitchen", "Hall"]
        assert first["links"] == [["sensor.batt"], [], []], (
            "linked sensors describe the parent device once — attaching them to "
            "every primary duplicates the role and Sber rejects the batch"
        )
        assert first["added"] == ["switch.a", "switch.c"], "a mid-batch failure must not lose the accepted ids"
        assert first["failed"] == [{"entity_id": "switch.b", "message": "backend said no"}], (
            "the failure record must name the entity and the reason"
        )
        assert first["hidden"] is False, "the dialog must stay open while something failed"
        assert "Added 2 of 3" in first["error"]
        assert first["loading"] is False
        assert len(first["events"]) == 1
        assert first["events"][0]["added_entity_ids"] == ["switch.a", "switch.c"]
        assert first["events"][0]["added_now"] == ["switch.a", "switch.c"]
        assert first["events"][0]["failed"] == [{"entity_id": "switch.b", "message": "backend said no"}]
        assert first["events"][0]["failed_count"] == 1
        assert first["events"][0]["added_count"] == 2

        second = out["round2"]
        assert second["sent"] == ["switch.b"], (
            "the retry re-sent an id the backend already accepted — that registers "
            "the entity twice and (with _linksAttached set) wipes its linked sensors"
        )
        assert second["links"] == [[]], "the retry must not re-attach the linked sensors"
        assert second["added"] == ["switch.a", "switch.c", "switch.b"]
        assert second["failed"] == []
        assert second["hidden"] is True, "a fully successful retry closes the dialog"
        assert second["events"][0]["added_entity_ids"] == ["switch.a", "switch.c", "switch.b"], (
            "the panel polls this list, so it must carry the whole session"
        )
        assert second["events"][0]["added_now"] == ["switch.b"], "only this submit's ids"
        assert second["events"][0]["failed"] == []
        assert out["addedSetReplaced"] is True, (
            "_added is a reactive property mutated in place — Lit compares by "
            "reference, so the retry label and the 'already added' badge freeze"
        )

        third = out["round3"]
        assert third["sent"] == [], "nothing is pending — re-clicking Finish must not call the backend"
        assert third["events"] == [], "a second wizard-complete would re-toast a batch already reported"
        assert third["hidden"] is True

    @requires_node
    def test_a_fully_failed_batch_registers_nothing(self, tmp_path):
        out = _run_wizard_scenario(
            tmp_path,
            'const wizard = makeWizard(() => "nope");\n'
            "await wizard._finish();\n"
            "console.log(JSON.stringify(snapshot(wizard)));\n",
        )
        assert out["sent"] == ["switch.a", "switch.b", "switch.c"], (
            "the first failure must not abort the rest of the batch"
        )
        assert out["added"] == []
        assert [f["entity_id"] for f in out["failed"]] == ["switch.a", "switch.b", "switch.c"]
        assert out["hidden"] is False
        assert "Nothing was added" in out["error"]
        assert out["events"][0]["added_entity_ids"] == []
        assert out["events"][0]["failed_count"] == 3

    @requires_node
    def test_links_are_attached_once_even_when_the_first_primary_fails(self, tmp_path):
        """``_linksAttached`` must track acceptance, not attempts."""
        out = _run_wizard_scenario(
            tmp_path,
            'const wizard = makeWizard((msg) => (msg.primary_entity_id === "switch.a" ? "nope" : null));\n'
            "await wizard._finish();\n"
            "console.log(JSON.stringify(snapshot(wizard)));\n",
        )
        assert out["links"] == [["sensor.batt"], ["sensor.batt"], []], (
            "the rejected call consumed the linked sensors — they must move to the "
            "next primary, and attach to exactly one accepted device"
        )
        assert out["added"] == ["switch.b", "switch.c"]

    @requires_node
    def test_finish_is_a_no_op_without_a_selected_device(self, tmp_path):
        out = _run_wizard_scenario(
            tmp_path,
            "const wizard = makeWizard(() => null);\n"
            'wizard._selectedDeviceId = "gone";\n'
            "await wizard._finish();\n"
            "console.log(JSON.stringify(snapshot(wizard)));\n",
        )
        assert out["sent"] == []
        assert out["events"] == []
        assert out["hidden"] is False

    def test_finish_skips_already_added_primaries(self):
        src = _read("components/sber-wizard.js")
        body = _method_body(src, "_finish")
        assert body is not None
        assert "_pendingPrimaries" in body, (
            "_finish re-sends the whole batch — a retry after a partial failure "
            "would register the accepted entities twice"
        )
        pending = _method_body(src, "_pendingPrimaries")
        assert pending is not None
        assert "this._added.has" in pending
        assert "this._added = new Set(" in body, (
            "accepted entities must be remembered — and by reassignment, since "
            "Lit cannot observe an in-place Set mutation"
        )
        assert "this._added.add(" not in body, "an in-place add leaves the reactive property stale"

    def test_finish_collects_per_entity_failures(self):
        body = _method_body(_read("components/sber-wizard.js"), "_finish")
        assert body is not None
        # try/catch must sit *inside* the loop, otherwise the first failure
        # aborts the rest of the batch with no record of what happened.
        loop = body[body.index("for (const primaryId") :]
        per_call_guard = "each add_ha_device call needs its own catch so one failure does not abort the batch"
        assert "try {" in loop, per_call_guard
        assert "catch (err)" in loop, per_call_guard
        assert "failed.push(" in loop

    def test_complete_event_carries_both_outcome_lists(self):
        body = _method_body(_read("components/sber-wizard.js"), "_emitComplete")
        assert body is not None
        # Match the object keys themselves — "failed" also occurs inside
        # "failed_count", so a bare substring check would pass without the list.
        keys = set(re.findall(r"^\s*([a-z_]+):", body, re.MULTILINE))
        for key in ("added_entity_ids", "failed", "failed_count", "added_count"):
            assert key in keys, f"wizard-complete must report {key}; got {sorted(keys)}"

    def test_wizard_stays_open_when_something_failed(self):
        body = _method_body(_read("components/sber-wizard.js"), "_finish")
        assert body is not None
        only_on_success = "the dialog must only close on a fully successful batch"
        assert "if (failed.length === 0) {" in body, only_on_success
        assert "this.hide();" in body, only_on_success

    def test_panel_surfaces_the_failures(self):
        body = _method_body(_read("sber-panel.js"), "_onWizardComplete")
        assert body is not None
        surfaced = "the panel must tell the user which entities failed, not just refresh"
        assert "d.failed" in body, surfaced
        assert '"error"' in body, surfaced
        named = "the toast must name the offending entities and the reason"
        assert "f.entity_id" in body, named
        assert "f.message" in body, named


# --------------------------------------------------------------------------- #
# Mutations are confirmed by polling, never by a blind sleep
# --------------------------------------------------------------------------- #

# Panel methods that mutate backend state and must confirm the result.
POLLING_METHODS = [
    ("sber-panel.js", "_removeEntities"),
    ("sber-panel.js", "_setOverride"),
    ("sber-panel.js", "_clearAll"),
    ("sber-panel.js", "_onToolbarAutoLink"),
    ("sber-panel.js", "_onToolbarImport"),
    ("sber-panel.js", "_onLinksSaved"),
    ("sber-panel.js", "_onWizardComplete"),
]


class TestNoBlindDelays:
    """``setTimeout(r, 1500)`` after a mutation is a race, not synchronisation."""

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_no_hardcoded_sleep_before_a_refetch(self, path):
        """No module may await a fixed-length sleep."""
        offenders = re.findall(r"setTimeout\(\s*r\s*,\s*(\d+)\s*\)", _read(path))
        assert not offenders, (
            f"{path}: blind sleep of {offenders} ms — poll the backend for the "
            "expected change instead of guessing how long it takes"
        )

    @pytest.mark.parametrize(("path", "method"), POLLING_METHODS)
    def test_mutation_confirms_via_polling(self, path, method):
        body = _method_body(_read(path), method)
        assert body is not None, f"{path}: {method} is gone"
        assert "_refreshUntil" in body, f"{path}: {method} does not wait for the mutation to become visible"

    def test_detail_dialog_polls_after_save(self):
        src = _read("components/sber-detail-dialog.js")
        assert "_reloadUntilSaved" in _method_body(src, "_onSave")
        body = _method_body(src, "_reloadUntilSaved")
        assert body is not None
        assert "RELOAD_TIMEOUT_MS" in body
        assert "RELOAD_INTERVAL_MS" in body
        assert "this.open" in body, "polling must stop when the user closes the dialog"

    @requires_node
    def test_detail_dialog_reload_waits_for_the_saved_values(self, tmp_path):
        """Drive the shipped ``_reloadUntilSaved`` with a lagging backend."""
        method = _method_source(_read("components/sber-detail-dialog.js"), "_reloadUntilSaved")
        old = {"entity_id": "light.a", "redefinitions": {"name": "Old", "room": "", "home": ""}}
        new = {"entity_id": "light.a", "redefinitions": {"name": "New", "room": "Hall", "home": ""}}
        other = {"entity_id": "light.b", "redefinitions": {"name": "New", "room": "Hall", "home": ""}}
        driver = (
            "const RELOAD_INTERVAL_MS = 1;\nconst RELOAD_TIMEOUT_MS = 120;\n"
            "function makeDialog(states) {\n"
            "  let fetches = 0;\n"
            "  const dialog = {\n"
            "    open: true,\n"
            "    isConnected: true,\n"
            "    _data: null,\n"
            "    get fetches() { return fetches; },\n"
            "    async _fetchDetail() {"
            " dialog._data = states[Math.min(fetches, states.length - 1)]; fetches += 1;"
            " if (dialog.onFetch) dialog.onFetch(dialog); },\n"
            f"    {method},\n"
            "  };\n"
            "  return dialog;\n"
            "}\n"
            f"const OLD = {json.dumps(old)}, NEW = {json.dumps(new)}, OTHER = {json.dumps(other)};\n"
            f"const WANT = {json.dumps({'name': 'New', 'room': 'Hall', 'home': ''})};\n"
            "const out = {};\n"
            "const lagging = makeDialog([OLD, OLD, NEW]);\n"
            'out.lagging = { ok: await lagging._reloadUntilSaved("light.a", WANT), fetches: lagging.fetches };\n'
            "const stuck = makeDialog([OLD]);\n"
            'out.stuck = { ok: await stuck._reloadUntilSaved("light.a", WANT), retried: stuck.fetches > 1 };\n'
            "const closed = makeDialog([OLD, NEW]);\n"
            "closed.onFetch = (d) => { d.open = false; };\n"
            'out.closed = { ok: await closed._reloadUntilSaved("light.a", WANT), fetches: closed.fetches };\n'
            "const swapped = makeDialog([OTHER, NEW]);\n"
            'out.swapped = { ok: await swapped._reloadUntilSaved("light.a", WANT), fetches: swapped.fetches };\n'
            "const broken = makeDialog([OLD, NEW]);\n"
            'broken.onFetch = (d) => { d._error = "ws closed"; };\n'
            'out.broken = { ok: await broken._reloadUntilSaved("light.a", WANT), fetches: broken.fetches };\n'
            "console.log(JSON.stringify(out));\nprocess.exit(0);\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["lagging"] == {"ok": True, "fetches": 3}, (
            "the dialog stopped before the saved values came back — a redefinition "
            "the backend has not applied yet would be rendered as saved"
        )
        assert out["stuck"] == {"ok": False, "retried": True}, "a save that never lands must not report success"
        assert out["closed"] == {"ok": False, "fetches": 1}, "closing the dialog must stop the poll"
        assert out["swapped"] == {"ok": False, "fetches": 1}, (
            "a payload describing a different entity was accepted as proof of this "
            "save — its redefinitions happen to match, but they are not ours"
        )
        assert out["broken"] == {"ok": False, "fetches": 1}, "a failing fetch is not 'not yet' — stop polling"

    @pytest.mark.parametrize(("path", "method"), POLLING_METHODS)
    def test_mutation_uses_the_polling_result(self, path, method):
        """Discarding the boolean means reporting success after a timeout.

        ``_setOverride``'s "auto" branch is the documented exception: the
        mapper may legitimately land on the same category, so "unchanged"
        is not a failure to confirm.
        """
        body = _method_body(_read(path), method)
        assert body is not None
        used = re.search(r"(?:(?:const|let)\s+)?\w+\s*=\s*await this\._refreshUntil", body)
        assert used, f"{path}: {method} throws away what _refreshUntil returned"

    @requires_node
    def test_refresh_until_stops_as_soon_as_the_change_lands(self, tmp_path):
        """One fetch when the predicate holds; more while it does not."""
        src = _read("sber-panel.js")
        driver = (
            "const POLL_INTERVAL_MS = 1;\nconst POLL_TIMEOUT_MS = 2000;\n"
            "function makePanel(states) {\n"
            "  return {\n"
            "    isConnected: true,\n"
            "    fetches: 0,\n"
            "    _devices: [],\n"
            "    _devicesExtra: {},\n"
            "    async _fetchAll() { this._devices = states[Math.min(this.fetches, states.length - 1)];"
            " this.fetches += 1; },\n"
            f"    {_method_source(src, '_refreshUntil')},\n"
            "  };\n"
            "}\n"
            "const out = {};\n"
            "const immediate = makePanel([[{ entity_id: 'a' }]]);\n"
            "out.immediate = { ok: await immediate._refreshUntil((d) => d.length === 1),"
            " fetches: immediate.fetches };\n"
            "const late = makePanel([[], [], [{ entity_id: 'a' }]]);\n"
            "out.late = { ok: await late._refreshUntil((d) => d.length === 1), fetches: late.fetches };\n"
            "const never = makePanel([[]]);\n"
            "const t0 = Date.now();\n"
            "const hung = Symbol('hung');\n"
            "const verdict = await Promise.race([\n"
            "  never._refreshUntil(() => false, { timeout: 60, interval: 1 }),\n"
            "  new Promise((r) => setTimeout(() => r(hung), 2000)),\n"
            "]);\n"
            "out.never = { ok: verdict === hung ? 'never returned' : verdict,"
            " elapsedUnder: Date.now() - t0 < 2000, fetches: never.fetches > 1 };\n"
            "const boom = makePanel([[]]);\n"
            "out.throwing = { ok: await boom._refreshUntil(() => { throw new Error('x'); }) };\n"
            "const gone = makePanel([[], [{ entity_id: 'a' }]]);\n"
            "gone.isConnected = false;\n"
            "out.detached = { ok: await gone._refreshUntil((d) => d.length === 1), fetches: gone.fetches };\n"
            "console.log(JSON.stringify(out));\n"
            # A regression that never terminates would keep the loop (and node)
            # alive forever; exit explicitly so the assertion reports it fast.
            "process.exit(0);\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["immediate"] == {"ok": True, "fetches": 1}, "must not poll once the state is already there"
        assert out["late"]["ok"] is True
        assert out["late"]["fetches"] == 3, "must keep re-reading until the change appears"
        assert out["never"] == {"ok": False, "elapsedUnder": True, "fetches": True}, (
            "a change that never lands must time out instead of looping forever"
        )
        assert out["throwing"] == {"ok": False}, "a throwing predicate must not strand the panel"
        assert out["detached"] == {"ok": False, "fetches": 1}, "a detached panel must stop polling after the first read"


# --------------------------------------------------------------------------- #
# Each per-command poll predicate, executed against scripted backend states
# --------------------------------------------------------------------------- #

# Everything the mutating handlers touch, so the shipped bodies run verbatim.
_PANEL_METHODS = [
    "_fetchAll",
    "_refreshUntil",
    "_reportUnconfirmed",
    "_countLinks",
    "_removeEntities",
    "_setOverride",
    "_clearAll",
    "_onToolbarAutoLink",
    "_onToolbarImport",
    "_onLinksSaved",
    "_onWizardComplete",
]

# ``snapshots`` is the sequence the backend returns from successive
# ``sber_mqtt_bridge/devices`` reads (the last entry repeats forever), so a
# predicate that accepts the pre-mutation state shows up as a lower read
# count — which is exactly the regression a substring assert cannot see.
_PANEL_HARNESS = """
const POLL_INTERVAL_MS = 1;
const POLL_TIMEOUT_MS = 150;

function makePanel(snapshots, opts = {}) {
  let reads = 0;
  const panel = {
    isConnected: true,
    _devices: [],
    _devicesExtra: {},
    _status: null,
    _loading: false,
    _error: "",
    toasts: [],
    calls: [],
    get reads() { return reads; },
    get deviceCalls() {
      return panel.calls.filter((c) => c.type === "sber_mqtt_bridge/devices").length;
    },
    hass: {
      callWS: async (msg) => {
        panel.calls.push(msg);
        if (msg.type === "sber_mqtt_bridge/devices") {
          if (opts.devicesError) throw new Error(opts.devicesError);
          const snap = snapshots[Math.min(reads, snapshots.length - 1)];
          reads += 1;
          return {
            devices: snap.devices,
            total: snap.total === undefined ? snap.devices.length : snap.total,
          };
        }
        if (msg.type === "sber_mqtt_bridge/status") return { connected: true };
        return opts.result || {};
      },
    },
    _showToast(message, type) { panel.toasts.push([message, type]); },
    __METHODS__
  };
  return panel;
}

function report(panel) {
  return {
    reads: panel.reads,
    deviceCalls: panel.deviceCalls,
    devices: panel._devices.map((d) => d.entity_id),
    error: panel._error,
    loading: panel._loading,
    toasts: panel.toasts,
    mutations: panel.calls
      .filter((c) => !c.type.endsWith("/devices") && !c.type.endsWith("/status"))
      .map((c) => c.type),
  };
}
"""


def _run_panel_scenario(tmp_path: Path, body: str) -> dict:
    """Execute ``body`` against the shipped panel mutation handlers in node."""
    harness = _PANEL_HARNESS.replace(
        "__METHODS__",
        _methods_as_object_body(_read("sber-panel.js"), _PANEL_METHODS),
    )
    return _run_node(tmp_path, harness + body + "process.exit(0);\n")


def _device(entity_id: str, **extra: object) -> str:
    """Render one device object for a node snapshot."""
    return json.dumps({"entity_id": entity_id, **extra})


class TestPollPredicates:
    """Each predicate must reject the pre-mutation snapshot and accept the next.

    ``_refreshUntil``'s loop is covered above; these drive the predicates
    the loop is *given*, which is where an inverted or degraded comparison
    hides — it still polls, it just accepts the stale answer.
    """

    @requires_node
    def test_removal_is_not_accepted_while_the_entity_is_still_listed(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a')}, {_device('light.b')}] }},\n"
            f"  {{ devices: [{_device('light.b')}] }},\n"
            "]);\n"
            'await panel._removeEntities(["light.a"]);\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2, (
            "the first read still lists light.a — accepting it means the table "
            "keeps showing a device the user just removed"
        )
        assert out["devices"] == ["light.b"]
        assert out["error"] == ""
        assert out["loading"] is False

    @requires_node
    def test_removal_that_never_lands_is_reported(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a')}, {_device('light.b')}] }},\n"
            "]);\n"
            'await panel._removeEntities(["light.a"]);\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] > 1, "the panel must actually retry"
        assert "did not confirm" in out["error"], (
            "a mutation that never became visible must be surfaced, not silently swallowed"
        )

    @requires_node
    def test_override_is_not_accepted_with_the_previous_category(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', sber_category='relay')}] }},\n"
            f"  {{ devices: [{_device('light.a', sber_category='relay')}] }},\n"
            f"  {{ devices: [{_device('light.a', sber_category='socket')}] }},\n"
            "]);\n"
            'await panel._setOverride("light.a", "socket");\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 3, "the predicate accepted a snapshot that still carried the old category"
        assert out["error"] == ""

    @requires_node
    def test_override_to_a_different_category_is_not_accepted(self, tmp_path):
        """Landing on some *other* category is not the one that was asked for."""
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', sber_category='valve')}] }},\n"
            "]);\n"
            'await panel._setOverride("light.a", "socket");\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] > 1
        assert "Category socket" in out["error"]

    @requires_node
    def test_auto_override_never_claims_an_unconfirmed_failure(self, tmp_path):
        """Reverting to "auto" may resolve to the same category — that is fine."""
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', sber_category='relay')}] }},\n"
            "]);\n"
            'await panel._setOverride("light.a", "auto");\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["error"] == "", "an unchanged category after revert-to-auto is not an error"
        assert out["mutations"] == ["sber_mqtt_bridge/set_override"]

    @requires_node
    def test_clear_all_waits_for_the_counter_too(self, tmp_path):
        """An empty ``devices`` list with a non-zero ``total`` is mid-rebuild."""
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            "  { devices: [], total: 3 },\n"
            "  { devices: [], total: 0 },\n"
            "]);\n"
            "await panel._clearAll();\n"
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2
        assert out["error"] == ""

    @requires_node
    def test_auto_link_waits_for_the_link_count_to_move(self, tmp_path):
        linked = {"battery": "sensor.batt"}
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', linked_entities={})}] }},\n"
            f"  {{ devices: [{_device('light.a', linked_entities={})}] }},\n"
            f"  {{ devices: [{_device('light.a', linked_entities=linked)}] }},\n"
            "], { result: { linked_count: 1, devices_affected: 1 } });\n"
            "await panel._onToolbarAutoLink();\n"
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 3, "the panel must not report links the backend has not applied yet"
        assert out["toasts"] == [["Auto-linked 1 sensor(s) to 1 device(s)", "success"]]

    @requires_node
    def test_auto_link_with_nothing_to_do_does_not_poll(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([{ devices: [] }], { result: { linked_count: 0 } });\n"
            "await panel._onToolbarAutoLink();\n"
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 1, "nothing changed — one read is enough"
        assert out["toasts"][0][1] == "info"

    @requires_node
    def test_import_waits_for_the_new_total(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            "  { devices: [], total: 0 },\n"
            f"  {{ devices: [{_device('light.a')}, {_device('light.b')}], total: 2 }},\n"
            "]);\n"
            'await panel._onToolbarImport({ detail: { config: { exposed_entities: ["light.a", "light.b"] } } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2
        assert out["toasts"] == [["Config imported successfully", "success"]]

    @requires_node
    def test_import_that_never_shows_up_is_not_reported_as_success(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([{ devices: [], total: 0 }]);\n"
            'await panel._onToolbarImport({ detail: { config: { exposed_entities: ["light.a"] } } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["toasts"][0][1] != "success", "an unconfirmed import must not claim success"
        assert "did not report" in out["toasts"][0][0]

    @requires_node
    def test_links_saved_rejects_a_swap_with_the_same_key_count(self, tmp_path):
        """The regression the in-code comment forbids: counting instead of comparing."""
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', linked_entities={'battery': 'sensor.old'})}] }},\n"
            f"  {{ devices: [{_device('light.a', linked_entities={'battery': 'sensor.new'})}] }},\n"
            "]);\n"
            'await panel._onLinksSaved({ detail: { entity_id: "light.a", links: { battery: "sensor.new" } } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2, (
            "sensor.old -> sensor.new keeps the key count identical; a count-only "
            "predicate accepts the stale map and the dialog closes on old data"
        )
        assert out["toasts"] == [["Entity links updated", "success"]]

    @requires_node
    def test_links_saved_rejects_a_stale_superset(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', linked_entities={'battery': 'sensor.new', 'signal': 'sensor.s'})}] }},\n"
            f"  {{ devices: [{_device('light.a', linked_entities={'battery': 'sensor.new'})}] }},\n"
            "]);\n"
            'await panel._onLinksSaved({ detail: { entity_id: "light.a", links: { battery: "sensor.new" } } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2, "a removed role must be gone before the save counts as applied"

    @requires_node
    def test_links_saved_that_never_lands_is_not_a_success_toast(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a', linked_entities={'battery': 'sensor.old'})}] }},\n"
            "]);\n"
            'await panel._onLinksSaved({ detail: { entity_id: "light.a", links: { battery: "sensor.new" } } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["toasts"][0][1] != "success"
        assert "old" in out["toasts"][0][0]

    @requires_node
    def test_wizard_batch_waits_for_every_added_entity(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([\n"
            f"  {{ devices: [{_device('light.a')}] }},\n"
            f"  {{ devices: [{_device('light.a')}, {_device('light.b')}] }},\n"
            "]);\n"
            "await panel._onWizardComplete({ detail: {"
            ' added_entity_ids: ["light.a", "light.b"], failed: [], linked_count: 0 } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["reads"] == 2, "half the batch showing up is not the batch showing up"
        assert out["toasts"] == [["Added 2 devices", "success"]]

    @requires_node
    def test_wizard_failures_are_named_in_the_toast(self, tmp_path):
        out = _run_panel_scenario(
            tmp_path,
            "const panel = makePanel([{ devices: [] }]);\n"
            "await panel._onWizardComplete({ detail: { added_entity_ids: [], failed: ["
            ' { entity_id: "light.x", message: "not allowed" } ], linked_count: 0 } });\n'
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["toasts"][0][1] == "error"
        assert "light.x" in out["toasts"][0][0]
        assert "not allowed" in out["toasts"][0][0]

    @requires_node
    @pytest.mark.parametrize(
        ("label", "call"),
        [
            ("remove", 'await panel._removeEntities(["light.a"]);'),
            ("override", 'await panel._setOverride("light.a", "socket");'),
            ("clear_all", "await panel._clearAll();"),
        ],
    )
    def test_a_failing_backend_stops_the_poll_immediately(self, tmp_path, label, call):
        """An erroring fetch is not "not yet" — retrying it 150x helps nobody.

        ``_devices`` is pre-populated with what the table was already
        showing, so the predicate cannot be trivially satisfied by the empty
        list a failed fetch leaves behind.
        """
        out = _run_panel_scenario(
            tmp_path,
            'const panel = makePanel([{ devices: [] }], { devicesError: "ws closed" });\n'
            'panel._devices = [{ entity_id: "light.a", sber_category: "relay", linked_entities: {} }];\n'
            "panel._devicesExtra = { total: 1 };\n"
            f"{call}\n"
            "console.log(JSON.stringify(report(panel)));\n",
        )
        assert out["deviceCalls"] == 1, (
            f"{label}: the panel kept re-reading a backend that is answering with errors — "
            "an error is not 'the mutation has not landed yet'"
        )
        assert out["error"] == "ws closed", "the real backend error must stay on screen, not be overwritten"


# --------------------------------------------------------------------------- #
# One shared subscription to the message feed
# --------------------------------------------------------------------------- #


class TestSingleMessageSubscription:
    """DevTools and Replay render the same feed — they must share one socket."""

    def test_only_the_bus_talks_to_subscribe_messages(self):
        owners = [path for path in _relative_js_modules() if '"sber_mqtt_bridge/subscribe_messages"' in _read(path)]
        assert owners == ["message-bus.js"], (
            f"{owners} each open their own subscription to the same broadcast feed — "
            "route them through message-bus.js instead"
        )

    @pytest.mark.parametrize("name", BUS_CONSUMERS)
    def test_consumers_use_the_bus(self, name):
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        assert "message-bus.js" in src, f"{name} must consume the shared bus"
        assert "connection.subscribeMessage" not in src, (
            f"{name} subscribes directly again — that is a second socket for the same feed"
        )
        assert "bus: { type: Object }" in src, f"{name} must accept the bus from the panel"

    def test_panel_owns_and_passes_the_bus(self):
        panel = _read("sber-panel.js")
        assert "message-bus.js" in panel
        assert panel.count(".bus=${messageBus}") == len(BUS_CONSUMERS), (
            "the panel must hand the same bus instance to every consumer"
        )

    @requires_node
    def test_bus_multiplexes_one_subscription(self, tmp_path):
        """Two listeners, one WS subscription, identical buffers."""
        driver = (
            'import { createMessageBus } from "./message-bus.mjs";\n'
            "let opened = 0, closed = 0, push = null;\n"
            "const hass = { connection: { subscribeMessage: async (cb) => {"
            " opened += 1; push = cb; return () => { closed += 1; }; } } };\n"
            "const bus = createMessageBus(3);\n"
            "const a = [], b = [];\n"
            "const offA = bus.subscribe(hass, (m) => a.push(m.length));\n"
            "const offB = bus.subscribe(hass, (m) => b.push(m.length));\n"
            "await new Promise((r) => setTimeout(r, 10));\n"
            "const out = { opened, active: bus.active, listeners: bus.listenerCount };\n"
            "push({ snapshot: [{ id: 1 }] });\n"
            "push({ message: { id: 2 } });\n"
            "out.a = [...a]; out.b = [...b];\n"
            "out.bothSeeSameBuffer = bus.messages.length === 2;\n"
            "push({ message: { id: 3 } });\n"
            "push({ message: { id: 4 } });\n"
            "out.capped = bus.messages.length;\n"
            "out.oldestDropped = bus.messages[0].id;\n"
            "bus.clear();\n"
            "out.cleared = bus.messages.length;\n"
            "offA();\n"
            "out.stillOpenAfterOneLeaves = { closed, active: bus.active };\n"
            "offA();\n"
            "out.doubleReleaseIsNoop = bus.listenerCount;\n"
            "offB();\n"
            "out.closedWhenLastLeaves = { closed, active: bus.active };\n"
            "bus.subscribe(hass, () => {});\n"
            "await new Promise((r) => setTimeout(r, 10));\n"
            "out.reopened = opened;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"message-bus.mjs": _read("message-bus.js")})
        assert out["opened"] == 1, "two listeners must share a single subscription"
        assert out["active"] is True
        assert out["listeners"] == 2
        assert out["a"] == out["b"] == [1, 2], "every listener must see every update"
        assert out["bothSeeSameBuffer"] is True
        assert out["capped"] == 3, "the shared buffer must stay capped"
        assert out["oldestDropped"] == 2, "the cap must drop the oldest message first"
        assert out["cleared"] == 0
        assert out["stillOpenAfterOneLeaves"] == {"closed": 0, "active": True}, (
            "one component leaving must not kill the feed for the other"
        )
        assert out["doubleReleaseIsNoop"] == 1, "releasing twice must not drop the other listener"
        assert out["closedWhenLastLeaves"] == {"closed": 1, "active": False}, (
            "the subscription must be released when nobody is listening"
        )
        assert out["reopened"] == 2, "a new listener must re-open the feed"

    @requires_node
    def test_bus_drops_a_subscription_that_lost_its_listeners_in_flight(self, tmp_path):
        """Detaching during the round-trip must not leak the socket."""
        driver = (
            'import { createMessageBus } from "./message-bus.mjs";\n'
            "let closed = 0;\n"
            "const hass = { connection: { subscribeMessage: async () => {"
            " await new Promise((r) => setTimeout(r, 20)); return () => { closed += 1; }; } } };\n"
            "const bus = createMessageBus();\n"
            "const off = bus.subscribe(hass, () => {});\n"
            "off();\n"
            "await new Promise((r) => setTimeout(r, 60));\n"
            "console.log(JSON.stringify({ closed, active: bus.active, listeners: bus.listenerCount }));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"message-bus.mjs": _read("message-bus.js")})
        assert out == {"closed": 1, "active": False, "listeners": 0}

    @requires_node
    def test_bus_reports_subscribe_failures_to_listeners(self, tmp_path):
        driver = (
            'import { createMessageBus } from "./message-bus.mjs";\n'
            "const hass = { connection: { subscribeMessage: async () => {"
            ' throw new Error("boom"); } } };\n'
            "const bus = createMessageBus();\n"
            "const errors = [];\n"
            "bus.subscribe(hass, () => {}, (e) => errors.push(e.message));\n"
            "await new Promise((r) => setTimeout(r, 20));\n"
            "console.log(JSON.stringify({ errors, active: bus.active }));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"message-bus.mjs": _read("message-bus.js")})
        assert out == {"errors": ["boom"], "active": False}, "a failed subscribe must reach the component, not vanish"

    @requires_node
    def test_manual_log_fetch_and_clear_go_through_the_bus(self, tmp_path):
        """A private buffer is exactly the divergence the bus was built to remove.

        Runs the shipped ``_fetchLog``/``_clearLog`` with a real bus and a
        second listener standing in for Replay: whatever DevTools pulls or
        drops must be visible to it.
        """
        src = (COMPONENTS / "sber-devtools.js").read_text(encoding="utf-8")
        methods = _methods_as_object_body(src, ["_fetchLog", "_clearLog"])
        driver = (
            'import { createMessageBus } from "./message-bus.mjs";\n'
            "const bus = createMessageBus();\n"
            "const hassStub = { connection: { subscribeMessage: async () => () => {} } };\n"
            "const replay = [];\n"
            "bus.subscribe(hassStub, (m) => replay.push(m.map((x) => x.id)));\n"
            "const devtools = {\n"
            "  bus,\n"
            "  _messages: [],\n"
            '  _logError: "stale",\n'
            "  calls: [],\n"
            "  hass: { callWS: async (msg) => {\n"
            "    devtools.calls.push(msg.type);\n"
            '    if (devtools.boom) throw new Error("ws closed");\n'
            '    if (msg.type === "sber_mqtt_bridge/message_log") return { messages: [{ id: 1 }, { id: 2 }] };\n'
            "    return {};\n"
            "  } },\n"
            f"  {methods}\n"
            "};\n"
            "bus.subscribe(hassStub, (m) => { devtools._messages = m; });\n"
            "const out = {};\n"
            "await devtools._fetchLog();\n"
            "out.afterFetch = { replay: replay.at(-1), own: devtools._messages.map((m) => m.id),"
            " error: devtools._logError };\n"
            "await devtools._clearLog();\n"
            "out.afterClear = { replay: replay.at(-1), own: devtools._messages.map((m) => m.id),"
            " calls: [...devtools.calls] };\n"
            "devtools.boom = true;\n"
            "bus.replace([{ id: 9 }]);\n"
            "await devtools._fetchLog();\n"
            "out.afterFailure = { replay: replay.at(-1), error: devtools._logError };\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"message-bus.mjs": _read("message-bus.js")})
        assert out["afterFetch"]["replay"] == [1, 2], (
            "the manual message_log fetch landed in a private field — Replay still "
            "renders the old buffer, which is the divergence the bus removed"
        )
        assert out["afterFetch"]["own"] == [1, 2]
        assert out["afterFetch"]["error"] == "", "a successful fetch must drop the previous error"
        assert out["afterClear"]["replay"] == [], "clearing the log must empty every consumer's view"
        assert out["afterClear"]["own"] == []
        assert out["afterClear"]["calls"] == [
            "sber_mqtt_bridge/message_log",
            "sber_mqtt_bridge/clear_message_log",
        ]
        assert out["afterFailure"] == {"replay": [9], "error": "ws closed"}, (
            "a failed fetch must report the error and leave the shared buffer alone"
        )


# --------------------------------------------------------------------------- #
# No dead exports, no duplicated dialog CSS, one clipboard helper
# --------------------------------------------------------------------------- #

SHARED_STYLE_CONSUMERS = ["sber-wizard.js", "sber-link-dialog.js", "sber-toolbar.js"]


class TestSharedModules:
    """Helpers live in one place and every export has a consumer."""

    @pytest.mark.parametrize("path", ["utils.js", "message-bus.js", "shared-styles.js"])
    def test_no_dead_exports(self, path):
        """An export nobody imports is dead weight that drifts out of sync."""
        src = _read(path)
        exported = _exported_names(src)
        assert exported, f"{path}: expected at least one export"

        # A name counts as used when it appears anywhere in the frontend or in
        # this test suite outside of its own `export` line.
        consumers = [_read(other) for other in _relative_js_modules() if other != path]
        consumers.append("\n".join(line for line in src.splitlines() if not line.startswith("export")))
        consumers.append(Path(__file__).read_text(encoding="utf-8"))
        haystack = "\n".join(consumers)
        dead = sorted(name for name in exported if not re.search(rf"\b{re.escape(name)}\b", haystack))
        assert not dead, f"{path}: dead export(s) {dead} — delete them or wire them up"

    @pytest.mark.parametrize("name", SHARED_STYLE_CONSUMERS)
    def test_dialog_and_button_css_is_not_re_declared(self, name):
        """Six local copies of ``.btn`` drifted apart — keep exactly one."""
        src = (COMPONENTS / name).read_text(encoding="utf-8")
        assert "shared-styles.js" in src, f"{name} must compose the shared styles"
        # Responsive overrides inside @media are deltas, not second definitions.
        base = _strip_media_blocks(src)
        duplicated = [rule for rule in (".btn {", ".btn-primary {", ".dialog-header {") if rule in base]
        assert not duplicated, f"{name} re-declares {duplicated} — those live in shared-styles.js now"

    def test_shared_styles_define_the_common_rules(self):
        src = _read("shared-styles.js")
        for rule in (".btn {", ".btn-primary {", ".dialog-header {", ".overlay {"):
            assert rule in src, f"shared-styles.js must define {rule}"

    def test_single_focus_helper(self):
        """Four copies of the shadow-DOM focus walk is four places to fix."""
        owners = [path for path in _relative_js_modules() if re.search(r"function deepActiveElement", _read(path))]
        assert owners == ["utils.js"], f"{owners} re-implement deepActiveElement — import it from utils.js"
        consumers = [
            path for path in _relative_js_modules() if "deepActiveElement" in _read(path) and path != "utils.js"
        ]
        assert set(consumers) == {
            "components/sber-detail-dialog.js",
            "components/sber-link-dialog.js",
            "components/sber-toolbar.js",
            "components/sber-wizard.js",
        }, f"every modal must manage focus through the shared helper; got {sorted(consumers)}"

    def test_single_clipboard_helper(self):
        """Two hand-rolled copy helpers meant two different fallback behaviours."""
        owners = [path for path in _relative_js_modules() if "navigator.clipboard" in _read(path)]
        assert owners == ["utils.js"], f"{owners} re-implement the clipboard fallback"
        assert "document.execCommand" in _read("utils.js"), (
            "the fallback for insecure contexts must survive the consolidation"
        )

    @requires_node
    def test_deep_active_element_descends_through_shadow_roots(self, tmp_path):
        """``document.activeElement`` stops at the outermost custom element.

        Without the descent every dialog would restore focus to the panel
        host instead of the control the user activated — the page scrolls
        back to the top and the focus ring lands nowhere useful.
        """
        driver = (
            'import { deepActiveElement } from "./utils.mjs";\n'
            'const button = { name: "row-button" };\n'
            'const row = { name: "row", shadowRoot: { activeElement: button } };\n'
            'const panel = { name: "panel", shadowRoot: { activeElement: row } };\n'
            "const out = {};\n"
            "globalThis.document = { activeElement: panel };\n"
            "out.nested = deepActiveElement().name;\n"
            'globalThis.document = { activeElement: { name: "plain" } };\n'
            "out.flat = deepActiveElement().name;\n"
            'globalThis.document = { activeElement: { name: "empty-shadow", shadowRoot: { activeElement: null } } };\n'
            "out.emptyShadow = deepActiveElement().name;\n"
            "globalThis.document = { activeElement: null };\n"
            "out.none = deepActiveElement();\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"utils.mjs": _read("utils.js")})
        assert out["nested"] == "row-button", "focus inside two shadow roots must be resolved, not the host"
        assert out["flat"] == "plain"
        assert out["emptyShadow"] == "empty-shadow", "a shadow root with nothing focused is the answer itself"
        assert out["none"] is None

    @requires_node
    def test_copy_text_falls_back_when_the_clipboard_api_is_unavailable(self, tmp_path):
        """Plain-HTTP HA installs have no ``navigator.clipboard``."""
        driver = (
            'import { copyText } from "./utils.mjs";\n'
            "const calls = [];\n"
            "const node = { value: '', style: {}, select() { calls.push('select'); } };\n"
            "globalThis.document = { createElement: () => node,"
            " body: { appendChild: () => calls.push('append'), removeChild: () => calls.push('remove') },"
            " execCommand: (c) => { calls.push(c); return true; } };\n"
            "const setNavigator = (v) => Object.defineProperty(globalThis, 'navigator',"
            " { value: v, configurable: true });\n"
            "setNavigator({});\n"
            "const okLegacy = await copyText('hello');\n"
            "const legacyCalls = [...calls];\n"
            "calls.length = 0;\n"
            "setNavigator({ clipboard: { writeText: async () => { throw new Error('denied'); } } });\n"
            "const okDenied = await copyText('hello');\n"
            "const deniedCalls = [...calls];\n"
            "calls.length = 0;\n"
            "globalThis.document.execCommand = () => false;\n"
            "const failed = await copyText('hello');\n"
            "console.log(JSON.stringify({ okLegacy, legacyCalls, okDenied, deniedCalls, failed,"
            " removedNode: calls.includes('remove'), value: node.value }));\n"
        )
        out = _run_node(tmp_path, driver, extra_files={"utils.mjs": _read("utils.js")})
        assert out["okLegacy"] is True, "no clipboard API must not mean no copy"
        assert out["legacyCalls"] == ["append", "select", "copy", "remove"]
        assert out["okDenied"] is True, "a rejected writeText must fall back, not fail"
        assert out["deniedCalls"] == ["append", "select", "copy", "remove"]
        assert out["failed"] is False, "a failing execCommand must be reported"
        assert out["removedNode"] is True, "the scratch textarea must always be removed"
        assert out["value"] == "hello"


# --------------------------------------------------------------------------- #
# Cache-busting reaches the whole import graph
# --------------------------------------------------------------------------- #


class TestCacheBusting:
    """``?v=`` must not stop at the component layer."""

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_no_static_import_of_lit_base(self, path):
        src = _read(path)
        assert not re.search(r'^import .* from "\.{1,2}/lit-base\.js";', src, re.MULTILINE), (
            f"{path}: a static import drops the ?v= query, so the browser keeps "
            "serving the cached lit bundle after an upgrade"
        )

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_every_dynamic_import_carries_the_version(self, path):
        unversioned = [
            spec
            for spec in re.findall(r"import\(`([^`]+)`\)", _read(path))
            if "${_q}" not in spec and "${VERSION_QUERY}" not in spec
        ]
        assert not unversioned, f"{path}: {unversioned} imported without the ?v= query"

    def test_lit_base_forwards_the_query_to_the_vendor_bundle(self):
        src = _read("lit-base.js")
        assert "import(`./vendor/lit.js${VERSION_QUERY}`)" in src

    @requires_node
    def test_version_query_reaches_the_vendor_module(self, tmp_path):
        """Import lit-base with a version and watch what vendor/lit.js receives."""
        stub = (
            "globalThis.__seen = globalThis.__seen || [];\n"
            "globalThis.__seen.push(new URL(import.meta.url).search);\n"
            "export const LitElement = class {};\n"
            "export const html = null, css = null, ReactiveElement = null, CSSResult = null,\n"
            "  unsafeCSS = null, nothing = null, noChange = null, render = null, svg = null, mathml = null;\n"
        )
        driver = (
            'const mod = await import("./lit-base.mjs?v=9.9.9");\n'
            "console.log(JSON.stringify({ seen: globalThis.__seen, own: mod.VERSION_QUERY }));\n"
        )
        out = _run_node(
            tmp_path,
            driver,
            extra_files={
                "lit-base.mjs": _read("lit-base.js").replace("./vendor/lit.js", "./vendor/lit.mjs"),
                "vendor/lit.mjs": stub,
            },
        )
        assert out == {"seen": ["?v=9.9.9"], "own": "?v=9.9.9"}, (
            "the vendored lit bundle was fetched without the cache-busting query"
        )

    @requires_node
    def test_a_missing_vendor_export_fails_loudly(self, tmp_path):
        """Destructuring a dynamic import loses the link-time error.

        ``export ... from`` used to fail immediately, naming the symbol.
        Without a guard, a re-vendored bundle that dropped a name yields
        ``undefined`` and the first component dies with the useless
        "class extends value undefined is not a constructor".
        """
        names = [
            "LitElement",
            "html",
            "css",
            "ReactiveElement",
            "CSSResult",
            "unsafeCSS",
            "nothing",
            "noChange",
            "render",
            "svg",
            "mathml",
        ]
        driver_lines = ["const out = {};"]
        for dropped in ("css", "LitElement", "mathml"):
            kept = [n for n in names if n != dropped]
            stub = "".join(f"export const {n} = {{}};\n" for n in kept)
            (tmp_path / "vendor").mkdir(parents=True, exist_ok=True)
            (tmp_path / f"lit-base-{dropped}.mjs").write_text(
                _read("lit-base.js").replace("./vendor/lit.js", f"./vendor/{dropped}-missing.mjs"),
                encoding="utf-8",
            )
            (tmp_path / "vendor" / f"{dropped}-missing.mjs").write_text(stub, encoding="utf-8")
            driver_lines.append(
                f'try {{ await import("./lit-base-{dropped}.mjs");'
                f' out["{dropped}"] = "imported without complaint"; }}'
                f' catch (e) {{ out["{dropped}"] = e.message; }}'
            )
        driver_lines.append("console.log(JSON.stringify(out));")
        out = _run_node(tmp_path, "\n".join(driver_lines) + "\n")
        for dropped in ("css", "LitElement", "mathml"):
            assert dropped in out[dropped], (
                f"lit-base swallowed a missing {dropped!r} export instead of naming it: {out[dropped]!r}"
            )
            assert "vendor" in out[dropped]


# --------------------------------------------------------------------------- #
# Table rows survive HTML parsing
# --------------------------------------------------------------------------- #


class TestDeviceTableRows:
    """``<tr><custom-element>`` is foster-parented out of the table."""

    def test_rows_are_not_wrapped_in_a_tr(self):
        src = _read("components/sber-device-table.js")
        body = src[src.index("<tbody>") : src.index("</tbody>")]
        assert "<sber-entity-row" in body, "the table must still render rows"
        assert "<tr" not in body, (
            "a <tr> around <sber-entity-row> is foster-parented by the HTML parser: "
            "the custom element lands outside the table and the class binding on the "
            "orphaned <tr> never reaches it"
        )

    def test_row_state_class_is_applied_by_the_row_itself(self):
        src = _read("components/sber-entity-row.js")
        body = _method_body(src, "updated")
        assert body is not None, "sber-entity-row must set its own state class"
        assert 'classList.add("row-online")' in body
        assert 'classList.add("row-offline")' in body
        for selector in (":host(.row-online)", ":host(.row-offline)"):
            assert selector in src, f"{selector} styling must exist for the class to matter"

    def test_row_renders_as_a_table_row(self):
        """Without ``display: table-row`` the cells no longer line up."""
        assert "display: table-row;" in _read("components/sber-entity-row.js")


# --------------------------------------------------------------------------- #
# No native browser dialogs
# --------------------------------------------------------------------------- #


class TestNoNativeDialogs:
    """``confirm()``/``alert()`` are unstyled, blocking and suppressible."""

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_no_confirm_or_alert(self, path):
        offenders = re.findall(r"(?<![\w.$])(confirm|alert)\s*\(", _strip_comments(_read(path)))
        assert not offenders, f"{path}: native {sorted(set(offenders))}() — use the panel's own dialog/toast"

    def test_clear_all_asks_for_confirmation_in_panel(self):
        src = (COMPONENTS / "sber-toolbar.js").read_text(encoding="utf-8")
        assert 'role="dialog"' in src
        assert 'aria-modal="true"' in src
        assert 'e.key === "Escape"' in src, "the confirm dialog must be escapable"
        accept = _method_body(src, "_acceptConfirm")
        assert accept is not None
        assert 'this._dispatch("toolbar-clear-all")' in accept
        opener = _method_body(src, "_onClearAll")
        assert opener is not None
        assert "toolbar-clear-all" not in opener, "Clear All must not fire before the user confirms"

    def test_import_errors_reach_the_panel_toast(self):
        toolbar = (COMPONENTS / "sber-toolbar.js").read_text(encoding="utf-8")
        assert "toolbar-toast" in toolbar
        assert "@toolbar-toast=" in _read("sber-panel.js"), (
            "the panel must listen for toolbar toasts, otherwise the message is lost"
        )

    @requires_node
    def test_confirm_modal_restores_focus_and_traps_tab(self, tmp_path):
        """The replacement for ``confirm()`` must not be a worse citizen than it.

        ``confirm()`` at least gave focus back to the page; a home-grown
        modal that leaks Tab into the inert page behind it and drops focus
        on close fails WCAG 2.4.3/2.4.7 outright.
        """
        src = (COMPONENTS / "sber-toolbar.js").read_text(encoding="utf-8")
        methods = _methods_as_object_body(
            src,
            ["_onClearAll", "_closeConfirm", "_cancelConfirm", "_acceptConfirm", "_onConfirmKeydown"],
        )
        driver = (
            "const focusLog = [];\n"
            "function control(name) { return { name, focus() { focused = this; focusLog.push(name); } }; }\n"
            'const opener = control("clear-all-button");\n'
            'const cancelBtn = control("cancel");\n'
            'const acceptBtn = control("accept");\n'
            "let focused = opener;\n"
            "function deepActiveElement() { return focused; }\n"
            "function makeToolbar() {\n"
            "  return {\n"
            '    _confirming: "",\n'
            "    _returnFocusTo: null,\n"
            "    events: [],\n"
            "    shadowRoot: { querySelectorAll: (sel) =>"
            ' (sel === ".confirm button" ? [cancelBtn, acceptBtn] : []) },\n'
            "    _closeBulk() {},\n"
            "    _dispatch(name) { this.events.push(name); },\n"
            f"    {methods}\n"
            "  };\n"
            "}\n"
            "const out = {};\n"
            "const cancelled = makeToolbar();\n"
            "cancelled._onClearAll();\n"
            "out.opened = { confirming: cancelled._confirming,"
            " captured: cancelled._returnFocusTo?.name };\n"
            "focused = cancelBtn;\n"
            "focusLog.length = 0;\n"
            "cancelled._cancelConfirm();\n"
            "out.cancelled = { confirming: cancelled._confirming, focusLog: [...focusLog],"
            " events: cancelled.events, dangling: cancelled._returnFocusTo };\n"
            "const accepted = makeToolbar();\n"
            "focused = opener;\n"
            "accepted._onClearAll();\n"
            "focused = acceptBtn;\n"
            "focusLog.length = 0;\n"
            "accepted._acceptConfirm();\n"
            "out.accepted = { focusLog: [...focusLog], events: accepted.events };\n"
            "const trap = makeToolbar();\n"
            "function press(key, shiftKey, active) {\n"
            "  focused = active;\n"
            "  focusLog.length = 0;\n"
            "  let prevented = false;\n"
            "  trap._onConfirmKeydown({ key, shiftKey, preventDefault: () => { prevented = true; } });\n"
            "  return { prevented, focusLog: [...focusLog] };\n"
            "}\n"
            "out.tabFromLast = press('Tab', false, acceptBtn);\n"
            "out.shiftTabFromFirst = press('Tab', true, cancelBtn);\n"
            "out.tabFromFirst = press('Tab', false, cancelBtn);\n"
            "out.otherKey = press('a', false, cancelBtn);\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["opened"] == {"confirming": "clear-all", "captured": "clear-all-button"}, (
            "the opener must be captured before focus moves into the modal"
        )
        assert out["cancelled"]["confirming"] == ""
        assert out["cancelled"]["focusLog"] == ["clear-all-button"], (
            "cancelling left focus inside a modal that no longer exists"
        )
        assert out["cancelled"]["events"] == [], "Cancel must not clear anything"
        assert out["cancelled"]["dangling"] is None, "a stale opener reference would steal a later focus"
        assert out["accepted"]["focusLog"] == ["clear-all-button"], "accepting must return focus too"
        assert out["accepted"]["events"] == ["toolbar-clear-all"]
        assert out["tabFromLast"] == {"prevented": True, "focusLog": ["cancel"]}, (
            "Tab off the last button escaped into the page behind the overlay"
        )
        assert out["shiftTabFromFirst"] == {"prevented": True, "focusLog": ["accept"]}
        assert out["tabFromFirst"] == {"prevented": False, "focusLog": []}, (
            "Tab between the modal's own buttons must stay native"
        )
        assert out["otherKey"] == {"prevented": False, "focusLog": []}


# --------------------------------------------------------------------------- #
# Transient error banners must not outlive their cause
# --------------------------------------------------------------------------- #


class TestErrorBannersAreCleared:
    """An error left on screen after the next success is a lie."""

    @requires_node
    def test_copy_report_clears_a_previous_failure(self, tmp_path):
        method = _method_source((COMPONENTS / "sber-diagnose.js").read_text(encoding="utf-8"), "_copyReport")
        driver = (
            "let outcome = false;\n"
            "async function copyText() {\n"
            '  if (outcome === "throw") throw new Error("boom");\n'
            "  return outcome;\n"
            "}\n"
            "const view = {\n"
            '  _report: { verdict: "ok" },\n'
            '  _error: "",\n'
            f"  {method},\n"
            "};\n"
            "const out = {};\n"
            "await view._copyReport();\n"
            "out.afterFailure = view._error;\n"
            "outcome = true;\n"
            "await view._copyReport();\n"
            "out.afterSuccess = view._error;\n"
            'outcome = "throw";\n'
            "await view._copyReport();\n"
            "out.afterThrow = view._error;\n"
            "view._report = null;\n"
            "outcome = true;\n"
            "await view._copyReport();\n"
            "out.withoutReport = view._error;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["afterFailure"], "a failed copy must say so"
        assert out["afterSuccess"] == "", (
            "the banner from the earlier failure survived a successful copy — the "
            "user sees 'clipboard unavailable' while the text is on the clipboard"
        )
        assert "boom" in out["afterThrow"]
        assert out["withoutReport"] == out["afterThrow"], "no report means no copy and no state change"


# --------------------------------------------------------------------------- #
# Payload dumps: clipped explicitly and reversibly, never cropped by CSS
# --------------------------------------------------------------------------- #

# ``max-height`` + ``overflow-y: auto`` on a read-only payload dump is invisible
# on mobile (no persistent scrollbar): issue #44 was filed as "the integration
# emits JSON without closing braces" against a payload that was complete.
# A ``<textarea>`` is exempt — it carries a caret and a native scrollbar, so a
# bounded height reads as "keep typing", not as "the document ends here".
_CLIP_EXEMPT = {("components/sber-devtools.js", ".json-editor")}
_PAYLOAD_SELECTOR = re.compile(r"json|payload|\bcode\b|\braw\b|\bpre\b", re.IGNORECASE)
_CSS_RULE = re.compile(r"([.#a-zA-Z][^{};]*?)\s*\{([^{}]*)\}", re.DOTALL)
# ``<div class="...">${JSON.stringify(x, null, 2)}</div>`` — a hand-rolled dump.
_INLINE_JSON_DUMP = re.compile(r">\$\{[^}]*JSON\.stringify\([^)]*null,\s*2\)")
# What makes an element a payload dump regardless of what its class is called:
# it *is* a code surface, or it wraps one.
_PAYLOAD_MARKUP = re.compile(r"code-surface|sber-json-block|JSON\.stringify|<pre\b|<code\b")
# ... or the rule itself styles text like a dump.
_PAYLOAD_DECLARATION = re.compile(r"white-space:\s*pre|font-family:[^;]*monospace")
# How far past the opening tag we still consider "inside" the element.  Long
# enough to reach the payload it wraps, short enough not to swallow siblings.
_ELEMENT_WINDOW = 400

# Every payload dump the panel shows: how many blocks each view renders and how
# many of them suppress the block's own copy button.
JSON_BLOCK_CONSUMERS = [
    # Allowed values + dependencies; the dialog has no copy control of its own.
    ("components/sber-detail-dialog.js", 2, 0),
    # Raw summary; the header already offers "Copy report" for the whole report.
    ("components/sber-diagnose.js", 1, 1),
    # Raw config + raw state; each section header has its own Copy button.
    ("components/sber-devtools.js", 2, 2),
]

# Same table without the copy-control column, for the tests that ignore it.
JSON_BLOCK_COUNTS = [(path, count) for path, count, _ in JSON_BLOCK_CONSUMERS]


def _clipping_rules(src: str) -> list[tuple[str, str]]:
    """Return ``(selector, body)`` for every CSS rule that bounds its height."""
    return [
        (" ".join(selector.split()), body)
        for selector, body in _CSS_RULE.findall(_strip_comments(src))
        if "max-height" in body
    ]


def _json_block_tags(src: str) -> list[str]:
    """Return the opening ``<sber-json-block ...>`` tag of every payload block."""
    return re.findall(r"<sber-json-block\b[^>]*>", src)


def _elements_carrying_class(src: str, class_name: str) -> list[tuple[str, str]]:
    """Return ``(tag, window)`` for every template element using ``class_name``.

    ``window`` is the source right after the opening tag, i.e. what the element
    renders — enough to tell a wrapper around a payload from an unrelated box.
    """
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]*?class=\"([^\"]*)\"", src):
        classes = re.split(r"[\s$}{]+", match.group(2))
        if class_name in classes:
            found.append((match.group(1), src[match.start() : match.end() + _ELEMENT_WINDOW]))
    return found


def _cropped_payload_selectors(path: str) -> list[str]:
    """Return selectors in ``path`` that bound the height of a payload dump.

    A dump is recognised three ways, so renaming the class is not a way out:

    * the selector reads like one (``.json-viewer``, ``.raw``, ...),
    * the rule styles its content as code (``white-space: pre``, monospace),
    * the class is applied to — or wraps — a code surface in the template.
    """
    src = _read(path)
    offenders: list[str] = []
    for selector, body in _clipping_rules(src):
        if (path, selector) in _CLIP_EXEMPT:
            continue
        looks_like_a_dump = bool(_PAYLOAD_SELECTOR.search(selector) or _PAYLOAD_DECLARATION.search(body))
        if not looks_like_a_dump:
            for class_name in re.findall(r"\.([\w-]+)", selector):
                for tag, window in _elements_carrying_class(src, class_name):
                    # A textarea keeps a caret and a native scrollbar.
                    if tag != "textarea" and (tag in {"pre", "code"} or _PAYLOAD_MARKUP.search(window)):
                        looks_like_a_dump = True
                        break
        if looks_like_a_dump:
            offenders.append(selector)
    return offenders


def _real_allowed_values() -> dict:
    """Build the ``allowed_values`` block of issue #44's chandelier.

    Taken from the shipped device class rather than hand-written, so the
    fixture cannot drift away from what the dialog actually receives.
    """
    entity = LightEntity({"entity_id": "light.svet_v_zale_main_light", "name": "Свет в зале"})
    entity.fill_by_ha_state(
        {
            "state": "on",
            "attributes": {
                "brightness": 180,
                "color_temp_kelvin": 3000,
                "min_color_temp_kelvin": 2000,
                "max_color_temp_kelvin": 6535,
                "supported_color_modes": ["color_temp", "hs"],
                "color_mode": "color_temp",
                "hs_color": [30, 80],
            },
        }
    )
    return entity.create_allowed_values_list()


_JSON_BLOCK_METHODS = [
    "text",
    "lineCount",
    "isTruncatable",
    "hiddenLineCount",
    "visibleText",
    "_toggle",
    "_copy",
    "_setCopyState",
    "disconnectedCallback",
    "render",
]


def _json_block_harness() -> str:
    """Fake ``sber-json-block`` carrying the shipped collapse/copy methods.

    ``setTimeout``/``clearTimeout``/``copyText`` are shadowed at module scope so
    the driver can inspect pending timers and clipboard writes without waiting.
    ``html`` is shadowed by a tag function that flattens the template into a
    string, so the shipped ``render()`` can be asserted on directly instead of
    through a paraphrase of its markup.
    """
    src = _read("components/sber-json-block.js")
    collapsed = re.search(r"^const COLLAPSED_LINES = (\d+);", src, re.MULTILINE)
    assert collapsed, "COLLAPSED_LINES must stay a module-level constant"
    feedback = re.search(r"^const COPY_FEEDBACK_MS = (\d+);", src, re.MULTILINE)
    assert feedback, "COPY_FEEDBACK_MS must stay a module-level constant"
    return (
        f"const COLLAPSED_LINES = {collapsed.group(1)};\n"
        f"const COPY_FEEDBACK_MS = {feedback.group(1)};\n"
        "let timers = [];\n"
        "let nextTimer = 1;\n"
        "const setTimeout = (fn, ms) => { const id = nextTimer++; timers.push({ id, fn, ms }); return id; };\n"
        "const clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };\n"
        "let copyOk = true;\n"
        "const copied = [];\n"
        "const copyText = async (text) => { copied.push(text); return copyOk; };\n"
        "let superCalls = 0;\n"
        "const SUPER = { disconnectedCallback() { superCalls += 1; } };\n"
        # Flatten nested templates; event handlers become a marker.
        "const fmt = (v) => {\n"
        "  if (Array.isArray(v)) return v.map(fmt).join('');\n"
        "  if (typeof v === 'function') return '[handler]';\n"
        "  if (v === null || v === undefined || v === false) return '';\n"
        "  return String(v);\n"
        "};\n"
        "const html = (strings, ...values) =>\n"
        "  strings.raw.reduce((acc, s, i) => acc + s + (i < values.length ? fmt(values[i]) : ''), '');\n"
        "function makeBlock(value, opts = {}) {\n"
        "  const block = {\n"
        "    value,\n"
        "    label: 'label' in opts ? opts.label : 'Allowed Values',\n"
        "    placeholder: 'placeholder' in opts ? opts.placeholder : '',\n"
        "    hideCopy: opts.hideCopy === true,\n"
        "    _expanded: false,\n"
        '    _copyState: "",\n'
        "    _copyTimer: null,\n"
        f"    {_methods_as_object_body(src, _JSON_BLOCK_METHODS)}\n"
        "  };\n"
        "  /* super.disconnectedCallback() resolves through the prototype. */\n"
        "  Object.setPrototypeOf(block, SUPER);\n"
        "  return block;\n"
        "}\n"
    )


def _collapsed_lines() -> int:
    """The shipped collapse threshold."""
    match = re.search(r"^const COLLAPSED_LINES = (\d+);", _read("components/sber-json-block.js"), re.MULTILINE)
    assert match
    return int(match.group(1))


class TestPayloadDumpsAreNotSilentlyCropped:
    """Issue #44: a cropped payload was read as malformed JSON."""

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_no_payload_dump_is_cropped_by_css(self, path):
        """``max-height`` on a JSON/raw container hides content with no affordance.

        Detection is not by class name alone: ``.viewer { max-height: 500px }``
        around a payload is the same bug under a name the word list misses.
        """
        offenders = _cropped_payload_selectors(path)
        assert not offenders, (
            f"{path}: {offenders} bound a payload dump with max-height — mobile "
            "browsers draw no scrollbar, so the JSON looks truncated and invalid; "
            "render it through <sber-json-block> instead"
        )

    def test_the_shared_block_slices_content_instead_of_cropping_it(self):
        """The collapsed view must really contain less text, not merely show less."""
        src = _strip_comments(_read("components/sber-json-block.js"))
        assert "max-height" not in src, (
            "a CSS crop reintroduces the invisible-scrollbar bug — collapse by "
            "slicing the text so the hidden part is provably absent"
        )
        assert "COLLAPSED_LINES" in src

    @pytest.mark.parametrize("path", sorted(_relative_js_modules()))
    def test_no_component_pretty_prints_json_into_its_own_template(self, path):
        """One collapsible block; a private dump would skip the disclosure UI."""
        offenders = _INLINE_JSON_DUMP.findall(_read(path))
        assert not offenders, (
            f"{path}: {offenders} dumps pretty-printed JSON straight into the "
            "template — use <sber-json-block .value=${...}>"
        )

    @pytest.mark.parametrize(("path", "count"), JSON_BLOCK_COUNTS)
    def test_payload_views_render_the_shared_block(self, path, count):
        src = _read(path)
        assert src.count("<sber-json-block") == count, f"{path}: expected {count} payload block(s)"
        assert "./sber-json-block.js${_q}" in src, (
            f"{path}: renders <sber-json-block> without importing it — the tag "
            "never upgrades and the payload disappears"
        )

    @pytest.mark.parametrize(("path", "count", "hide_copy"), JSON_BLOCK_CONSUMERS)
    def test_copy_buttons_are_not_duplicated_on_a_payload(self, path, count, hide_copy):
        """``hide-copy`` exactly where the view already offers a copy control.

        Two "Copy" buttons next to one payload copy different things — the
        section's own button takes the whole report/payload, the block's takes
        the JSON.  A bug report then arrives with the wrong text attached,
        which is how issue #44 stayed ambiguous for so long.
        """
        tags = _json_block_tags(_read(path))
        assert len(tags) == count
        suppressed = [tag for tag in tags if re.search(r"\bhide-copy\b", tag)]
        assert len(suppressed) == hide_copy, (
            f"{path}: {len(suppressed)} of {count} payload block(s) hide their copy "
            f"button, expected {hide_copy} — a view either owns the copy control or "
            "delegates it to the block, never both"
        )
        if hide_copy:
            assert re.search(r">\s*Copy", _read(path)), (
                f"{path}: suppresses the block's copy button without offering one itself"
            )

    def test_devtools_payload_blocks_explain_an_empty_state(self):
        """The old ``:empty::before`` hint must survive as a placeholder."""
        tags = _json_block_tags(_read("components/sber-devtools.js"))
        placeholders = [re.search(r'placeholder="([^"]*)"', tag) for tag in tags]
        assert all(placeholders), (
            "a DevTools payload block starts empty — without a placeholder the "
            "user sees a blank box instead of 'Click the button above to load data'"
        )
        assert all("load data" in match.group(1) for match in placeholders if match)

    def test_devtools_composes_the_shared_code_surface(self):
        """The editor's monospace look now lives only in ``codeSurfaceStyles``."""
        src = _read("components/sber-devtools.js")
        assert re.search(r"return \[\s*codeSurfaceStyles\s*,", src), (
            "DevTools stopped composing codeSurfaceStyles — the editor loses its "
            "background, monospace font and padding in one silent step"
        )
        editors = re.findall(r'<textarea class="([^"]*)"', src)
        assert editors, "the raw config/state editors must stay <textarea>s"
        for classes in editors:
            assert "code-surface" in classes.split(), (
                f'<textarea class="{classes}"> dropped .code-surface — nothing else styles it now'
            )
        editor_rule = next(
            (body for selector, body in _clipping_rules(src) if selector == ".json-editor"),
            None,
        )
        assert editor_rule is not None
        for duplicated in ("font-family", "background:"):
            assert duplicated not in editor_rule, (
                f".json-editor re-declares {duplicated} — it must come from .code-surface only"
            )

    def test_the_toggle_is_a_keyboard_operable_disclosure_button(self):
        """Wave 5 accessibility: the new control must not be mouse-only."""
        src = _read("components/sber-json-block.js")
        toggle = re.search(r"<button\b[^>]*aria-expanded[^>]*>", src)
        assert toggle, "the expand control must be a native <button> (Enter/Space for free)"
        assert 'aria-controls="code"' in toggle.group(0), "the button must point at the region it expands"
        assert 'id="code"' in src, "aria-controls needs its target id inside the shadow root"
        assert 'aria-label="${this.label} payload"' in src, "the payload region needs an accessible name"
        assert "aria-live=" in src, "the copy outcome must be announced"
        assert not _clickable_without_keyboard(src), "every click target must have a keyboard path"

    def test_the_shared_code_surface_wraps_long_lines(self):
        """A horizontal scroll area is invisible on mobile for the same reason."""
        surface = re.search(r"codeSurfaceStyles = css`(.*?)`;", _read("shared-styles.js"), re.DOTALL)
        assert surface, "shared-styles.js must own the code surface"
        body = surface.group(1)
        assert "white-space: pre-wrap" in body
        assert "overflow-wrap: anywhere" in body
        assert "overflow-x" not in body, "long JSON must wrap, not scroll sideways"

    def test_the_code_surface_colours_are_a_locked_pair(self):
        """A themed background with a fixed foreground is an unreadable payload.

        Home Assistant defines no ``--code-editor-color``, so that half always
        resolves to the hard-coded light grey, while themes *do* set
        ``--code-editor-background-color``.  A theme choosing a light editor
        background would then paint #d4d4d4 on near-white (~1.3:1).  Both
        colours must therefore come from the same place.
        """
        surface = re.search(r"codeSurfaceStyles = css`(.*?)`;", _read("shared-styles.js"), re.DOTALL)
        assert surface
        body = _strip_comments(surface.group(1))
        background = re.search(r"\n\s*background(?:-color)?:\s*([^;]+);", body)
        color = re.search(r"\n\s*color:\s*([^;]+);", body)
        assert background, "the code surface must state its background"
        assert color, "the code surface must state its text colour"
        assert ("var(" in background.group(1)) == ("var(" in color.group(1)), (
            f"background {background.group(1)!r} and color {color.group(1)!r} do not "
            "come from the same source — one follows the theme, the other does not, "
            "so some theme renders the payload invisible"
        )
        assert "var(" not in background.group(1), "HA ships no --code-editor-color companion; keep the pair literal"
        fade = re.search(
            r"\.fade \{(.*?)\}",
            _strip_comments(_read("components/sber-json-block.js")),
            re.DOTALL,
        )
        assert fade, "the clipped view needs its fade"
        assert background.group(1).strip() in fade.group(1), (
            "the fade must end on the surface's own background, otherwise the last "
            "visible line dissolves into a different colour than the block"
        )

    def test_the_reported_payload_is_long_enough_to_be_collapsed(self):
        """Guards the fixture: a short payload would make the node tests vacuous."""
        text = json.dumps(_real_allowed_values(), indent=2)
        assert len(text.splitlines()) > _collapsed_lines()

    @requires_node
    def test_expanding_restores_the_whole_payload(self, tmp_path):
        """The real methods: collapsed slices, expanded is byte-identical JSON."""
        value = _real_allowed_values()
        driver = (
            _json_block_harness() + f"const VALUE = {json.dumps(value)};\n"
            "const out = {};\n"
            "const block = makeBlock(VALUE);\n"
            "const full = JSON.stringify(VALUE, null, 2);\n"
            "out.fullLines = full.split('\\n').length;\n"
            "out.truncatable = block.isTruncatable;\n"
            "out.collapsed = block.visibleText();\n"
            "out.hidden = block.hiddenLineCount;\n"
            "const parses = (t) => { try { JSON.parse(t); return true; } catch { return false; } };\n"
            "out.collapsedParses = parses(out.collapsed);\n"
            "block._toggle();\n"
            "out.expanded = block.visibleText();\n"
            "out.expandedHidden = block.hiddenLineCount;\n"
            "out.expandedIsFull = out.expanded === full;\n"
            "out.expandedParses = parses(out.expanded);\n"
            "block._toggle();\n"
            "out.recollapsed = block.visibleText() === out.collapsed;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        threshold = _collapsed_lines()
        collapsed_lines = out["collapsed"].split("\n")
        assert out["truncatable"] is True
        assert collapsed_lines[:threshold] == json.dumps(value, indent=2).split("\n")[:threshold]
        assert out["collapsed"].endswith("\n…"), "the clipped view must say it is clipped, in the text itself"
        assert len(collapsed_lines) == threshold + 1, (
            f"the collapsed view shows {len(collapsed_lines) - 1} payload lines, not "
            f"{threshold} — a slice that ignores its own threshold makes the "
            "'N more lines hidden' note count something else than the block shows"
        )
        assert out["hidden"] == out["fullLines"] - threshold
        # shown + hidden == everything: the note the user reads must add up.
        assert (len(collapsed_lines) - 1) + out["hidden"] == out["fullLines"], (
            f"{len(collapsed_lines) - 1} lines on screen + {out['hidden']} announced as "
            f"hidden != {out['fullLines']} lines of payload"
        )
        assert out["collapsedParses"] is False, (
            "the collapsed slice is genuinely incomplete JSON — precisely why it "
            "must be labelled instead of hidden behind an invisible scrollbar"
        )
        assert out["expandedIsFull"] is True, "expanding must reveal the payload verbatim"
        assert out["expandedParses"] is True, "the expanded payload must be valid, closing braces and all"
        assert out["expandedHidden"] == 0
        assert out["recollapsed"] is True, "collapsing again must return to the short form"

    @requires_node
    def test_short_payloads_are_shown_whole_without_a_toggle(self, tmp_path):
        """Boundary: exactly the threshold stays whole, one line more collapses."""
        threshold = _collapsed_lines()
        sizes = [0, 1, threshold - 1, threshold, threshold + 1]
        driver = (
            _json_block_harness() + "const line = (n) => Array.from({ length: n }, (_, i) => `l${i}`).join('\\n');\n"
            "const out = {};\n"
            f"for (const n of {json.dumps(sizes)}) {{\n"
            "  const block = makeBlock(n === 0 ? '' : line(n));\n"
            "  out[`n${n}`] = {\n"
            "    lines: block.lineCount,\n"
            "    truncatable: block.isTruncatable,\n"
            "    hidden: block.hiddenLineCount,\n"
            "    whole: block.visibleText() === block.text,\n"
            "  };\n"
            "}\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["n0"] == {"lines": 0, "truncatable": False, "hidden": 0, "whole": True}
        assert out["n1"] == {"lines": 1, "truncatable": False, "hidden": 0, "whole": True}
        assert out[f"n{threshold - 1}"]["truncatable"] is False
        assert out[f"n{threshold}"] == {
            "lines": threshold,
            "truncatable": False,
            "hidden": 0,
            "whole": True,
        }, "a payload that fits must not grow a pointless 'Show all' button"
        assert out[f"n{threshold + 1}"] == {
            "lines": threshold + 1,
            "truncatable": True,
            "hidden": 1,
            "whole": False,
        }, "one line over the threshold must already announce itself as clipped"

    def test_a_single_hidden_line_is_worded_in_the_singular(self):
        src = _read("components/sber-json-block.js")
        assert 'hidden === 1 ? "line" : "lines"' in src, "'1 more lines hidden' reads like a bug"

    @requires_node
    def test_the_markup_only_signals_hidden_content_when_there_is_some(self, tmp_path):
        """The shipped ``render()``, executed: every affordance tracks the state.

        A fade over a fully expanded payload is the same false "there is more
        below" hint the CSS crop gave — just prettier.
        """
        value = _real_allowed_values()
        threshold = _collapsed_lines()
        driver = (
            _json_block_harness() + f"const VALUE = {json.dumps(value)};\n"
            "const out = {};\n"
            "const line = (n) => Array.from({ length: n }, (_, i) => `l${i}`).join('\\n');\n"
            "out.emptyWithPlaceholder = makeBlock('', { placeholder: 'Click the button above "
            "to load data...' }).render();\n"
            "out.emptyDefault = makeBlock(null).render();\n"
            "const block = makeBlock(VALUE);\n"
            "out.collapsed = block.render();\n"
            "block._toggle();\n"
            "out.expanded = block.render();\n"
            f"out.oneHidden = makeBlock(line({threshold + 1})).render();\n"
            "out.short = makeBlock(line(3)).render();\n"
            "out.hideCopy = makeBlock(VALUE, { hideCopy: true }).render();\n"
            "const copying = makeBlock(VALUE);\n"
            "copying._copyState = 'Copy failed';\n"
            "out.copying = copying.render();\n"
            "out.fullLines = JSON.stringify(VALUE, null, 2).split('\\n').length;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)

        empty = out["emptyWithPlaceholder"]
        assert "Click the button above to load data..." in empty, (
            "an unloaded DevTools payload must explain itself — the old "
            ":empty::before hint has to survive as the block's placeholder"
        )
        assert "<pre" not in empty, "nothing to show means nothing to render as a payload"
        assert "<button" not in empty, "nothing to show means nothing to expand or copy"
        assert "No data" in out["emptyDefault"], "a block with no placeholder still needs a word"

        hidden = out["fullLines"] - threshold
        assert f"Show all {out['fullLines']} lines" in out["collapsed"]
        assert f"{hidden} more lines hidden" in out["collapsed"]
        assert 'class="fade"' in out["collapsed"], "the clipped view needs its 'continues below' hint"
        assert "aria-expanded=false" in out["collapsed"]
        assert "Copy JSON" in out["collapsed"]

        assert "Collapse" in out["expanded"]
        assert "aria-expanded=true" in out["expanded"]
        assert 'class="fade"' not in out["expanded"], (
            "a fade over a fully shown payload claims there is more text below — "
            "exactly the illusion issue #44 was filed about"
        )
        clip_note = re.compile(r"\d+ more lines? hidden")
        assert not clip_note.search(out["expanded"]), "nothing is hidden once expanded, so nothing may say so"

        assert "1 more line hidden" in out["oneHidden"], "'1 more lines hidden' reads like a bug"

        assert "<pre" in out["short"], "a short payload is still a payload"
        assert 'class="fade"' not in out["short"], "nothing is clipped, so nothing may fade out"
        assert "Show all" not in out["short"], "a payload that fits offers no disclosure control"
        assert not clip_note.search(out["short"])

        assert "Copy JSON" not in out["hideCopy"], "hide-copy must actually remove the button, not merely dim it"
        assert "Show all" in out["hideCopy"], "hide-copy must not take the disclosure control with it"

        assert "Copy failed" in out["copying"], "the copy outcome must reach the markup"

    @requires_node
    def test_copy_always_takes_the_whole_payload(self, tmp_path):
        """Copying the visible slice would paste JSON that really is broken."""
        value = _real_allowed_values()
        driver = (
            _json_block_harness() + f"const VALUE = {json.dumps(value)};\n"
            "const out = {};\n"
            "const block = makeBlock(VALUE);\n"
            "await block._copy();\n"
            "out.whileCollapsed = copied.at(-1);\n"
            "out.stateAfterCopy = block._copyState;\n"
            "block._toggle();\n"
            "await block._copy();\n"
            "out.whileExpanded = copied.at(-1);\n"
            "out.full = JSON.stringify(VALUE, null, 2);\n"
            "copyOk = false;\n"
            "await block._copy();\n"
            "out.failureState = block._copyState;\n"
            "out.pendingTimers = timers.length;\n"
            "timers.at(-1).fn();\n"
            "out.afterTimeout = block._copyState;\n"
            "out.timeoutMs = timers.length ? null : COPY_FEEDBACK_MS;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["whileCollapsed"] == out["full"], (
            "the collapsed block copied only what was on screen — the pasted JSON "
            "would be the truncated text the bug report was filed about"
        )
        assert out["whileExpanded"] == out["full"]
        assert out["stateAfterCopy"] == "Copied"
        assert out["failureState"] == "Copy failed", "a silent clipboard failure looks like a successful copy"
        assert out["pendingTimers"] == 1, (
            "each copy must replace the previous timer, otherwise the older one wipes the newer message early"
        )
        assert out["afterTimeout"] == "", "a stale 'Copy failed' outlives its cause"

    @requires_node
    def test_disconnect_cancels_the_pending_copy_timer(self, tmp_path):
        """A timer firing into a detached element is a leak and a stray render."""
        driver = (
            _json_block_harness() + "const out = {};\n"
            "const block = makeBlock({ a: 1 });\n"
            "await block._copy();\n"
            "out.beforeDisconnect = timers.length;\n"
            "block.disconnectedCallback();\n"
            "out.afterDisconnect = timers.length;\n"
            "out.handle = block._copyTimer;\n"
            "out.superCalls = superCalls;\n"
            "block.disconnectedCallback();\n"
            "out.idempotent = timers.length;\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["beforeDisconnect"] == 1
        assert out["afterDisconnect"] == 0, "the copy-feedback timer outlived the element"
        assert out["handle"] is None, "a stale handle would be cleared twice later"
        assert out["superCalls"] == 1, "LitElement's own disconnect bookkeeping must still run"
        assert out["idempotent"] == 0

    @requires_node
    def test_non_object_payloads_survive(self, tmp_path):
        """Strings pass through; nothing at all renders nothing; cycles do not throw."""
        driver = (
            _json_block_harness() + "const out = {};\n"
            "out.string = makeBlock('{\\n  \"a\": 1\\n}').text;\n"
            "out.stringLines = makeBlock('{\\n  \"a\": 1\\n}').lineCount;\n"
            "out.null = makeBlock(null).text;\n"
            "out.undefined = makeBlock(undefined).text;\n"
            "out.emptyLines = makeBlock(null).lineCount;\n"
            "out.emptyTruncatable = makeBlock(null).isTruncatable;\n"
            "out.emptyString = makeBlock('').lineCount;\n"
            "out.number = makeBlock(42).text;\n"
            "const circular = { name: 'loop' };\n"
            "circular.self = circular;\n"
            "try { out.circular = makeBlock(circular).text; } catch (e) { out.circular = `threw: ${e.message}`; }\n"
            "const long = 'x'.repeat(5000);\n"
            "const oneLine = makeBlock(long);\n"
            "out.oneLine = { lines: oneLine.lineCount, truncatable: oneLine.isTruncatable,"
            " whole: oneLine.visibleText() === long };\n"
            "console.log(JSON.stringify(out));\n"
        )
        out = _run_node(tmp_path, driver)
        assert out["string"] == '{\n  "a": 1\n}', "an already-formatted payload must not be re-encoded"
        assert out["stringLines"] == 3
        assert out["null"] == ""
        assert out["undefined"] == ""
        assert out["emptyLines"] == 0
        assert out["emptyTruncatable"] is False, "an empty payload must not offer a 'Show all' button"
        assert out["emptyString"] == 0
        assert out["number"] == "42"
        assert not out["circular"].startswith("threw:"), (
            "a circular payload must not blank the whole dialog: " + out["circular"]
        )
        assert out["oneLine"] == {"lines": 1, "truncatable": False, "whole": True}, (
            "a single very long line is not collapsible — it must be wrapped by CSS, not clipped"
        )
