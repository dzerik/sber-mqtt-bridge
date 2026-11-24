"""Execute the shipped no-build components and vendored Lit in Node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WWW = Path(__file__).resolve().parents[2] / "custom_components/sber_mqtt_bridge/www"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _render(tmp_path: Path, script: str, language: str = "en") -> dict:
    """Load complete production modules; only the browser shell is replaced."""
    shutil.copytree(WWW, tmp_path / "www")
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    translations = json.loads((WWW.parent / f"translations/{language}.json").read_text())["config_panel"]
    driver = """
globalThis.HTMLElement = class extends EventTarget {};
globalThis.document = { createTreeWalker: () => ({}) };
const registry = new Map();
globalThis.customElements = { define: (name, cls) => registry.set(name, cls) };
await import('./www/components/sber-entity-row.js');
await import('./www/components/sber-wizard.js');
const Row = registry.get('sber-entity-row');
const Wizard = registry.get('sber-wizard');
const dictionary = __TRANSLATIONS__;
const hass = { language: '__LANGUAGE__', localize: (key) => {
  const parts = key.split('.').slice(3);
  return parts.reduce((value, part) => value?.[part], dictionary);
} };
function text(node) {
  if (Array.isArray(node)) return node.map(text).join(' ');
  if (node?.strings) return node.strings.reduce((out, part, i) => out + part + text(node.values[i]), '');
  return node == null || typeof node === 'function' ? '' : String(node);
}
function listeners(node, event) {
  if (Array.isArray(node)) return node.flatMap((item) => listeners(item, event));
  if (!node?.strings) return [];
  const found = [];
  for (let i = 0; i < node.values.length; i++) {
    if (node.strings[i].trimEnd().endsWith('@' + event + '=')) found.push(node.values[i]);
    found.push(...listeners(node.values[i], event));
  }
  return found;
}
""".replace("__TRANSLATIONS__", json.dumps(translations)).replace("__LANGUAGE__", language)
    target = tmp_path / "driver.mjs"
    target.write_text(driver + script, encoding="utf-8")
    result = subprocess.run([NODE, str(target)], capture_output=True, text=True, timeout=60, check=True)  # noqa: S603
    return json.loads(result.stdout)


@pytest.mark.parametrize("domain", ["input_button", "scene"])
@pytest.mark.parametrize("language", ["en", "ru"])
def test_action_cards_explain_control_and_event_directions(tmp_path, domain, language):
    """Both choices must remain understandable in the wizard and category row."""
    out = _render(
        tmp_path,
        """
const entityId = '__DOMAIN__.test';
const wizard = new Wizard();
wizard.hass = hass;
const row = new Row();
row.hass = hass;
row.device = { entity_id: entityId, sber_category: 'relay', name: 'Test' };
row.categories = ['relay', 'scenario_button'];
const card = wizard._renderDeviceCard({ device_id: 'entity:' + entityId, name: 'Test', primary: { entity_id: entityId } });
const stopped = [];
listeners(card, 'click')[1]({ stopPropagation: () => stopped.push('click') });
listeners(card, 'keydown')[1]({ stopPropagation: () => stopped.push('keydown') });
console.log(JSON.stringify({ wizard: text(card), row: text(row.render()), stopped }));
""".replace("__DOMAIN__", domain),
        language,
    )
    for rendered in (out["wizard"], out["row"]):
        assert "Sber → HA" in rendered
        assert "HA → Sber" in rendered
        assert 'class="representation-info"' in rendered
        assert "title=" in rendered
        assert "aria-label=" in rendered
        assert "ⓘ" in rendered
        assert "input-boolean-hint" not in rendered
    assert out["stopped"] == ["click", "keydown"]


@pytest.mark.parametrize("category", ["relay", "scenario_button"])
@pytest.mark.parametrize("language", ["en", "ru"])
def test_wizard_explains_both_input_boolean_representations(tmp_path, category, language):
    """Removing the domain-specific card hint must hide essential choice guidance."""
    out = _render(
        tmp_path,
        """
const wizard = new Wizard();
wizard.hass = hass;
wizard._selectedCategory = __CATEGORY__;
const helper = { device_id: 'entity:input_boolean.guest', name: 'Guest',
  primary: { entity_id: 'input_boolean.guest', friendly_name: 'Guest' } };
const other = { ...helper, primary: { entity_id: 'switch.guest' } };
console.log(JSON.stringify({ helper: text(wizard._renderDeviceCard(helper)),
  other: text(wizard._renderDeviceCard(other)) }));
""".replace("__CATEGORY__", json.dumps(category)),
        language,
    )
    assert "relay" in out["helper"]
    assert "scenario_button" in out["helper"]
    assert "click" in out["helper"]
    assert "double_click" in out["helper"]
    assert ("voice" if language == "en" else "голос") in out["helper"].lower()
    assert 'class="representation-info"' in out["helper"]
    assert "title=" in out["helper"]
    assert "input-boolean-hint" not in out["helper"]
    assert "scenario_button" not in out["other"], "Other domains must retain their existing cards"


@pytest.mark.parametrize("category", ["relay", "scenario_button"])
@pytest.mark.parametrize("language", ["en", "ru"])
def test_row_tooltip_explains_input_boolean_and_category_change(tmp_path, category, language):
    """A compact info control keeps the category guidance available."""
    out = _render(
        tmp_path,
        """
const row = new Row();
row.hass = hass;
row.device = { entity_id: 'input_boolean.guest', sber_category: __CATEGORY__, name: 'Guest' };
row.categories = ['relay', 'scenario_button'];
const rendered = row.render();
const events = [];
row.addEventListener('override-changed', (event) => events.push(event.detail));
// The second change listener belongs to the category select, after the checkbox.
listeners(rendered, 'change')[1].call(row, { target: { value: 'relay' } });
const helper = text(rendered);
row.device = { entity_id: 'switch.guest', sber_category: __CATEGORY__ };
console.log(JSON.stringify({ helper, other: text(row.render()), events }));
""".replace("__CATEGORY__", json.dumps(category)),
        language,
    )
    assert "relay" in out["helper"]
    assert "scenario_button" in out["helper"]
    assert "double_click" in out["helper"]
    assert ("re-register" if language == "en" else "перерегистр") in out["helper"].lower()
    assert ("reconfigure" if language == "en" else "перенастро") in out["helper"].lower()
    assert 'class="representation-info"' in out["helper"]
    assert "title=" in out["helper"]
    assert "aria-label=" in out["helper"]
    assert "input-boolean-hint" not in out["helper"]
    assert "double_click" not in out["other"]
    assert "representation-info" not in out["other"]
    assert out["events"] == [{"entityId": "input_boolean.guest", "category": "relay"}]
