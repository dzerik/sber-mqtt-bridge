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
    "Time the gate needs to travel end to end. 0 disables it: the position then changes only when the contact sensor reports. With a value set, the gate reports \"opening\" / \"closing\" right after the impulse — and for that whole time the Sber app blocks its control button in both directions, so a movement cannot be interrupted from the app until the timer runs out.",
  "gate_options.auto_close_time": "Auto-close delay (seconds)",
  "gate_options.auto_close_time_description":
    "Enter the same delay your gate board uses to close the leaf after it was opened — the bridge cannot read that setting itself. 0 disables it. The countdown starts when the contact sensor reports the gate open, no matter who opened it: the app, a remote or a GSM call. When it runs out the gate reports \"closing\" until the sensor says otherwise, and the Sber app blocks its control button while that lasts. Set the leaf travel time as well: without it that \"closing\" is assumed to last 30 seconds, and a slower leaf is reported as open — with an active button — while it is still moving.",
  "gate_options.contact_stale":
    "The contact sensor is unavailable — the last known position is shown",
  "gate_options.missing_required_link_warning":
    'This gate has no position sensor linked, so it reports "closed" whatever the leaf does. Link a binary sensor in the "open_state" role.',
  "gate_options.save": "Save gate options",
  "gate_options.missing_required_role":
    "Link the gate position sensor (a binary sensor with device class garage door, door or opening) before adding this device",

  // --- kettle operation modes ---
  "kettle_options.title": "Kettle operation modes",
  "kettle_options.off_mode": '"Off" mode',
  "kettle_options.boil_mode": '"Boil" mode',
  "kettle_options.heat_mode": '"Heat to setpoint" mode',
  "kettle_options.mode_auto": "Detect automatically",
  "kettle_options.resolved": "In use: {mode}",
  "kettle_options.unresolved":
    "Not detected — the bridge falls back to turning the kettle on and off",
  "kettle_options.no_modes":
    "This kettle reports no operation modes, so the bridge switches it on and off directly.",
  "kettle_options.save": "Save kettle options",

  // --- stats ---
  "stats.uptime": "Uptime",
  "stats.messages_received": "Messages received",
  "stats.messages_sent": "Messages sent",
  "stats.commands": "Commands",
  "stats.config_requests": "Config requests",
  "stats.status_requests": "Status requests",
  "stats.sber_errors": "Sber errors",
  "stats.publish_errors": "Publish errors",
  "stats.reconnects": "Reconnects",
  "stats.entities_exposed": "Entities exposed",
  "stats.loading": "Loading status…",
  "stats.never_confirmed": "Never confirmed",
  "stats.never_confirmed_title": "Never confirmed by Sber",
  "stats.never_confirmed_hint": "Devices the Sber cloud has never once asked about. Survives restarts, so a device listed here is genuinely not getting through.",

  // --- json ---
  "json.copy": "Copy JSON",
  "json.copied": "Copied",
  "json.copy_failed": "Copy failed",
  "json.collapse": "Collapse",
  "json.expand": "Show all {lines} lines",

  // --- row ---
  "row.online": "Online",
  "row.offline": "Offline",
  "row.loading": "Loading…",
  "row.select": "Select {entity}",
  "row.details": "Show details for {entity}",
  "row.override": "Sber category override for {entity}",
  // --- toolbar ---
  "toolbar.clear_all_title": "Remove ALL exposed entities?",
  "toolbar.clear_all_warning": "Every device disappears from Sber. This cannot be undone.",
  "toolbar.cancel": "Cancel",
  "toolbar.clear_all": "Clear all",
  "toolbar.import_invalid_json": "Import failed: file is not valid JSON",
  "toolbar.add_device": "Add device",
  "toolbar.maintenance": "Maintenance",
  "toolbar.auto_link": "Auto-link sensors",
  "toolbar.publishing": "Publishing…",
  "toolbar.republish": "Re-publish",
  "toolbar.refresh": "Refresh",
  "toolbar.export": "Export",
  "toolbar.import": "Import",
  "toolbar.device_counter": "{total} devices ({known} known to Sber)",

  // --- connection phases (status card + toolbar) ---
  "phase.starting.label": "Starting…",
  "phase.starting.desc": "Waiting for Home Assistant to finish loading",
  "phase.connecting.label": "Connecting…",
  "phase.connecting.desc": "Establishing MQTT connection to Sber cloud",
  "phase.awaiting_ack.label": "Awaiting Sber…",
  "phase.awaiting_ack.desc": "Connected, config published — waiting for Sber to acknowledge",
  "phase.ready.label": "Ready",
  "phase.ready.desc": "Fully operational — accepting commands from Sber",
  "phase.disconnected.label": "Disconnected",
  "phase.disconnected.desc": "Not connected to Sber MQTT broker",

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
