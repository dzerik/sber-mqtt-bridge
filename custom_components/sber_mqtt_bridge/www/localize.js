/**
 * Sber MQTT Bridge — panel localization.
 *
 * The panel reads its strings from the integration's own translation
 * files, so a Russian user sees a Russian panel without us shipping a
 * second copy of every string in JavaScript.
 *
 * ## Why this works (checked against Home Assistant sources)
 *
 * Home Assistant serves translations per *category*, and `config_panel`
 * is one of the categories both sides know about:
 *
 * - backend: `homeassistant/helpers/translation.py` builds its cache from
 *   whatever top-level sections the integration's `translations/<lang>.json`
 *   actually contains, and `frontend/get_translations` will hand any of
 *   them to the client;
 * - frontend: `config_panel` is a member of `TranslationCategory`
 *   (`src/data/translation.ts`) — the very category ZHA's own config panel
 *   loads with `hass.loadBackendTranslation("config_panel", "zha")`;
 * - hassfest: `script/hassfest/translations.py` accepts an optional
 *   `config_panel` section of arbitrarily nested slug keys, so these
 *   strings pass validation like any other section.
 *
 * The catch is that the category is **not** loaded automatically: nothing
 * in the frontend fetches it for a custom panel. {@link ensurePanelTranslations}
 * does it once per language; until it resolves (and on a Home Assistant so
 * old it has no `loadBackendTranslation`) {@link t} falls back to the
 * English text baked into {@link EN_FALLBACK}.
 *
 * Home Assistant itself loads English first and overlays the requested
 * language on top, so a key that exists in `en.json` but not in `ru.json`
 * silently renders in English — no special handling needed here.
 *
 * ## How to add a string
 *
 * 1. Add the key to `strings.json` and `translations/en.json` under
 *    `config_panel.<block>.<key>` (both files, same English text).
 * 2. Add the Russian text to `translations/ru.json` under the same path.
 * 3. Add the same dotted key to {@link EN_FALLBACK} below with the English
 *    text — this is what shows before the fetch completes.
 * 4. Render it as `${t(this.hass, "block.key")}`.
 *
 * Keys must be `[a-z0-9_-]+` per hassfest, values must not contain HTML.
 */

/** Integration domain — first segment of every translation key. */
export const DOMAIN = "sber_mqtt_bridge";

/**
 * Home Assistant translation category carrying the panel's strings.
 *
 * See the module docstring: this is an officially supported section of
 * `strings.json`, not an invention of ours.
 */
export const CATEGORY = "config_panel";

/**
 * English text for every key the panel renders.
 *
 * Used before {@link ensurePanelTranslations} resolves and whenever the
 * backend has nothing for the key.  Keys are the dotted path below
 * `config_panel.` and must mirror `translations/en.json`.
 */
export const EN_FALLBACK = {
  // --- impulse gate settings (issue #53) ---
  "gate_options.title": "Impulse gate",
  "gate_options.invert_contact": "Inverted contact",
  "gate_options.invert_contact_description":
    'Enable when the linked contact sensor reports "on" while the gate is closed',
  "gate_options.impulse_service": "Impulse service",
  "gate_options.impulse_service_auto": "Automatic (toggle)",
  "gate_options.impulse_service_toggle": "switch.toggle",
  "gate_options.impulse_service_turn_on": "switch.turn_on",
  "gate_options.travel_time": "Leaf travel time (seconds)",
  "gate_options.travel_time_description":
    "Time the gate needs to travel end to end. 0 disables it: the position then changes only when the contact sensor reports. With a value set, the gate reports \"opening\" / \"closing\" right after the impulse until the sensor confirms.",
  "gate_options.contact_stale":
    "The contact sensor is unavailable — the last known position is shown",
  "gate_options.missing_required_link_warning":
    'This gate has no position sensor linked, so it reports "closed" whatever the leaf does. Link a binary sensor in the "open_state" role.',
  "gate_options.save": "Save gate options",
  "gate_options.missing_required_role":
    "Link the gate position sensor (a binary sensor with device class garage door, door or opening) before adding this device",

  // --- device detail dialog ---
  "detail_dialog.loading": "Loading…",
  "detail_dialog.close": "Close details",
  "detail_dialog.override": "Sber Override",
  "detail_dialog.overview": "Overview",
  "detail_dialog.sber_states": "Sber States (current)",
  "detail_dialog.linked_entities": "Linked Entities",
  "detail_dialog.model_config": "Sber Model Config",
  "detail_dialog.ha_attributes": "HA Attributes",
  "detail_dialog.device_registry": "HA Device Registry",
  "detail_dialog.saved": "Saved",
  "detail_dialog.error": "Error",
};

/** Language the in-flight/settled {@link _pending} load was started for. */
let _language = null;

/** Cached load promise, one per language. */
let _pending = null;

/**
 * Substitute `{name}` placeholders into a fallback string.
 *
 * Mirrors what `hass.localize` does for the translated variant, so a
 * string reads the same whether it came from the backend or from
 * {@link EN_FALLBACK}.
 *
 * @param {string} text - Template text.
 * @param {object} [placeholders] - Values keyed by placeholder name.
 * @returns {string} Text with placeholders replaced.
 */
function _fill(text, placeholders) {
  if (!placeholders) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    placeholders[name] === undefined ? match : String(placeholders[name]),
  );
}

/**
 * Translate a panel string.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {string} key - Dotted key below `config_panel.`, e.g.
 *   `"gate_options.title"`.
 * @param {object} [placeholders] - Values for `{name}` placeholders.
 * @returns {string} Localized text, English fallback, or the key itself
 *   when the key is unknown (loud enough to notice, quiet enough to ship).
 */
export function t(hass, key, placeholders) {
  const translated = hass?.localize?.(
    `component.${DOMAIN}.${CATEGORY}.${key}`,
    placeholders,
  );
  if (translated) return translated;
  const fallback = EN_FALLBACK[key];
  return fallback === undefined ? key : _fill(fallback, placeholders);
}

/**
 * Fetch the `config_panel` strings for the current language, once.
 *
 * Home Assistant only refetches categories that were loaded *without* an
 * integration filter when the user switches language, so the language is
 * tracked here and the fetch is repeated when it changes.
 *
 * Loading new resources replaces `hass` (and with it `hass.localize`),
 * which re-renders every component that holds it — so a re-render is only
 * forced for the caller that actually started a fetch, and only to cover
 * the case where the panel is not re-fed a fresh `hass`.
 *
 * Failures are swallowed on purpose: an untranslated panel beats a broken
 * one, and {@link t} already has English for every key.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {{requestUpdate?: () => void}} [element] - Component to re-render
 *   once the fetch completes.
 * @returns {Promise<void>} Resolves when the strings are available.
 */
export function ensurePanelTranslations(hass, element) {
  const language = hass?.language || "en";
  if (_pending && _language === language) return _pending;

  _language = language;
  const load = hass?.loadBackendTranslation;
  let fetching;
  try {
    /* `try` covers a synchronous throw as well as a rejection: this runs
     * from `updated()`, where an escaping error kills the render pass. */
    fetching =
      typeof load === "function"
        ? Promise.resolve(load.call(hass, CATEGORY, DOMAIN))
        : Promise.resolve(undefined);
  } catch {
    fetching = Promise.resolve(undefined);
  }
  _pending = fetching.then(
    () => undefined,
    () => undefined,
  );

  if (element?.requestUpdate) {
    _pending.then(() => element.requestUpdate());
  }
  return _pending;
}

/**
 * Drop the cached load state.
 *
 * Only meant for tests — production code has no reason to re-fetch.
 *
 * @returns {void}
 */
export function resetPanelTranslations() {
  _language = null;
  _pending = null;
}
