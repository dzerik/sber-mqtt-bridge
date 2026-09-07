/**
 * Sber MQTT Bridge — human names for Sber features.
 *
 * Every feature the bridge publishes has two names.  The identifier
 * (`light_colour_temp`) is what travels on the wire, what the validator
 * quotes and what the documentation URL ends with.  The title
 * («температура цвета») is what Sber prints on the very same feature's
 * reference page — and what the Salute app shows the user on their
 * phone.  Until now the panel only ever showed the first one.
 *
 * ## Where the titles come from
 *
 * Not from here.  They are scraped from
 * https://developers.sber.ru/docs/ru/smarthome/c2c into
 * `_generated/feature_labels.py` and served by the
 * `sber_mqtt_bridge/feature_labels` WebSocket command.  Copying 96
 * strings into JavaScript would create a second source of truth that
 * silently rots the next time Sber edits a page, so the panel asks the
 * backend instead — once per page load, not once per status poll.
 *
 * ## Why the titles are Russian only
 *
 * The C2C reference exists in Russian only, so there is no documented
 * English name to ship, and inventing one is worse than showing none:
 * a made-up "colour temperature" that disagrees with the app, the docs
 * and the validator helps nobody.  So the pair is shown by role
 * instead of by language:
 *
 * - a user whose Home Assistant speaks the language the titles are
 *   written in reads the title, with the identifier as the tooltip;
 * - everyone else reads the identifier — the same one they will find
 *   in the docs and in the log — with the documented title as the
 *   tooltip, since the Salute app on their phone shows that text no
 *   matter what language their Home Assistant is in.
 *
 * The backend states which language the titles are in, so the day an
 * English reference appears this file needs no change.
 *
 * ## Which of the two functions to call
 *
 * - {@link featureTitle} for a dense surface where the identifier has to
 *   stay put — a table cell, a chip in a row of chips.  The documented
 *   name goes into `title=`, where it costs no width and is available
 *   in every language.
 * - {@link featureLabel} where the name is meant to be read — the device
 *   card, a validator remark.  There the two swap places by language, as
 *   described above.
 *
 * ## Usage
 *
 * ```js
 * connectedCallback() {
 *   super.connectedCallback();
 *   ensureFeatureLabels(this.hass, this);
 * }
 * render() {
 *   const label = featureLabel(this.hass, "light_colour_temp");
 *   return html`<span title="${label.hint}">${label.text}</span>`;
 * }
 * ```
 */

/** WebSocket command serving the documented vocabulary. */
export const LABELS_COMMAND = "sber_mqtt_bridge/feature_labels";

/** Vocabulary in use: `{language, titles, enum_labels}`. */
let _labels = { language: "", titles: {}, enum_labels: {} };

/**
 * Fetch in flight, or the resolved promise of the fetch that succeeded.
 *
 * Cleared again when a fetch fails, so the failure costs one request and
 * not the vocabulary for the rest of the page's life.
 */
let _pending = null;

/** Whether a fetch has come back — successfully — at least once. */
let _settled = false;

/**
 * Ask the backend for the vocabulary, or decline to ask at all.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @returns {?Promise<void>} The fetch, or `null` when this `hass` cannot
 *   carry a WebSocket call — an unusable `hass` is not an answer, so it
 *   must not be cached as one.
 */
function _fetchLabels(hass) {
  const call = hass?.callWS;
  if (typeof call !== "function") return null;
  let fetching;
  try {
    /* `try` covers a synchronous throw as well as a rejection: this runs
     * from `connectedCallback`, where an escaping error stops the
     * component from ever attaching. */
    fetching = Promise.resolve(call.call(hass, { type: LABELS_COMMAND }));
  } catch {
    return null;
  }
  return fetching.then(
    (result) => {
      if (result && typeof result === "object") {
        _labels = {
          language: result.language || "",
          titles: result.titles || {},
          enum_labels: result.enum_labels || {},
        };
      }
      _settled = true;
    },
    () => {
      /* Release the cache instead of marking it settled: the next
       * component to connect asks again.  The panel is a SPA, so a
       * latched failure would last until the user reloads the whole page
       * — and the two ways this happens are transient by nature (the
       * first component connecting before `hass` is usable, and a panel
       * opened while the config entry is still loading, when the command
       * is not registered yet). */
      _pending = null;
    },
  );
}

/**
 * Fetch the documented vocabulary once per page.
 *
 * Failures are swallowed on purpose, exactly like the panel's
 * translation loader: a feature list showing identifiers is a worse
 * panel, a feature list throwing during render is no panel at all.
 * Unlike the translation loader, a failure here is not final — see
 * {@link _fetchLabels}.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {{requestUpdate?: () => void}} [element] - Component to
 *   re-render once the fetch completes.  Only components that asked
 *   while the fetch was still in flight are re-rendered; a component
 *   created afterwards already renders from the cache.
 * @returns {Promise<void>} Resolves when the vocabulary is available, or
 *   when this attempt has given up on it.
 */
export function ensureFeatureLabels(hass, element) {
  if (!_settled && !_pending) {
    _pending = _fetchLabels(hass);
  }
  const pending = _pending || Promise.resolve();
  if (!_settled && element?.requestUpdate) {
    pending.then(() => element.requestUpdate());
  }
  return pending;
}

/**
 * Documented human name of a feature, if Sber publishes one.
 *
 * Language-independent on purpose: callers that only need a tooltip
 * (a dense table, where a full title would not fit) want the
 * documented text whatever the interface language is.
 *
 * @param {string} key - Sber feature identifier, e.g. `"light_colour_temp"`.
 * @returns {string} The documented title, or `""` when the feature has
 *   none — an event-only feature added after the last snapshot, or a
 *   typo.
 */
export function featureTitle(key) {
  const title = _labels.titles[key];
  return typeof title === "string" ? title : "";
}

/**
 * Documented human name of one ENUM value of a feature.
 *
 * @param {string} key - Sber feature identifier, e.g. `"hvac_work_mode"`.
 * @param {string} value - Enum value, e.g. `"cooling"`.
 * @returns {string} The documented title, or `""` when Sber's page for
 *   the feature lists the value without describing it.
 */
export function enumValueTitle(key, value) {
  const title = _labels.enum_labels[key]?.[value];
  return typeof title === "string" ? title : "";
}

/**
 * Whether the interface language matches the language of the titles.
 *
 * Compared on the base subtag, so `ru-RU` counts as Russian.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @returns {boolean} True when the user reads the documented titles
 *   natively.
 */
function _readsLabelLanguage(hass) {
  if (!_labels.language) return false;
  const language = hass?.language || "en";
  return language.split("-")[0].toLowerCase() === _labels.language.toLowerCase();
}

/**
 * Primary text and tooltip for a feature, chosen by interface language.
 *
 * See the module docstring for why the two swap places instead of the
 * title being translated.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {string} key - Sber feature identifier.
 * @returns {{text: string, hint: string}} `text` is what to render,
 *   `hint` what to put in `title=` (empty when there is nothing to add).
 */
export function featureLabel(hass, key) {
  const title = featureTitle(key);
  if (!title) return { text: key, hint: "" };
  return _readsLabelLanguage(hass) ? { text: title, hint: key } : { text: key, hint: title };
}

/**
 * Same as {@link featureLabel}, for one ENUM value of a feature.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {string} key - Sber feature identifier.
 * @param {string} value - Enum value.
 * @returns {{text: string, hint: string}} Text to render and tooltip.
 */
export function enumValueLabel(hass, key, value) {
  const title = enumValueTitle(key, value);
  if (!title) return { text: value, hint: "" };
  return _readsLabelLanguage(hass) ? { text: title, hint: value } : { text: value, hint: title };
}

/**
 * Drop the cached vocabulary.
 *
 * Only meant for tests — production code has no reason to re-fetch a
 * table that changes only when the integration is upgraded.
 *
 * @returns {void}
 */
export function resetFeatureLabels() {
  _labels = { language: "", titles: {}, enum_labels: {} };
  _pending = null;
  _settled = false;
}
