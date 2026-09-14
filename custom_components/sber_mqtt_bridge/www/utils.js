/**
 * Sber MQTT Bridge -- Shared utilities.
 *
 * Provides slugify (cyrillic-aware), Salut name validation and the single
 * clipboard helper used by every component.
 *
 * Dependency-free on purpose: ``tests/hacs/test_www_frontend.py`` executes
 * this module in bare node to compare it against the Python source of truth.
 */

/**
 * Transliterate a Cyrillic string to Latin and produce a slug
 * suitable for Sber device IDs (lowercase a-z, 0-9, underscore).
 *
 * @param {string} text - Source text (typically Russian).
 * @returns {string} Slugified identifier.
 */
export function slugify(text) {
  const map = {
    "\u0430": "a", "\u0431": "b", "\u0432": "v", "\u0433": "g", "\u0434": "d",
    "\u0435": "e", "\u0451": "yo", "\u0436": "zh", "\u0437": "z", "\u0438": "i",
    "\u0439": "y", "\u043A": "k", "\u043B": "l", "\u043C": "m", "\u043D": "n",
    "\u043E": "o", "\u043F": "p", "\u0440": "r", "\u0441": "s", "\u0442": "t",
    "\u0443": "u", "\u0444": "f", "\u0445": "kh", "\u0446": "ts", "\u0447": "ch",
    "\u0448": "sh", "\u0449": "sch", "\u044A": "", "\u044B": "y", "\u044C": "",
    "\u044D": "e", "\u044E": "yu", "\u044F": "ya",
  };
  return text
    .toLowerCase()
    .split("")
    .map((c) => map[c] ?? c)
    .join("")
    .replace(/[^a-z0-9]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

/**
 * Salut-friendly name pattern: 3-33 characters, Cyrillic letters,
 * digits, spaces and hyphens.
 *
 * MUST stay byte-for-byte equivalent to ``_SALUT_NAME`` in
 * ``custom_components/sber_mqtt_bridge/name_utils.py`` (the Python side
 * is the source of truth).  ``tests/hacs/test_www_frontend.py``
 * fails the build when the two diverge.
 */
export const SALUT_NAME_RE = /^[\u0430-\u044F\u0451\u0410-\u042F\u04010-9 \-]{3,33}$/;

/**
 * Validate a device name for the Salut voice assistant.
 *
 * Rules: 3-33 characters, only Cyrillic letters, digits, spaces and
 * hyphens (Sber's own docs show names like "\u0421\u043C\u0430\u0440\u0442-\u0442\u0435\u043B\u0435\u0432\u0438\u0437\u043E\u0440").
 *
 * @param {string} name - Candidate device name.
 * @returns {boolean} True if the name is valid.
 */
export function isValidSalutName(name) {
  return typeof name === "string" && SALUT_NAME_RE.test(name);
}

/**
 * Resolve the element that really has focus, descending into shadow roots.
 *
 * ``document.activeElement`` only reports the outermost custom element, so a
 * naive capture would restore focus to the panel host instead of the control
 * the user actually activated (WCAG 2.4.3).
 *
 * @returns {Element|null} Deepest focused element.
 */
export function deepActiveElement() {
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) {
    el = el.shadowRoot.activeElement;
  }
  return el;
}

/**
 * Copy text to the clipboard, falling back to the legacy path.
 *
 * ``navigator.clipboard`` is undefined in insecure contexts (plain-HTTP
 * Home Assistant installs are common) and rejects when the permission is
 * denied, so both failure modes fall through to a hidden textarea.
 *
 * @param {string} text - Text to place on the clipboard.
 * @returns {Promise<boolean>} True when the text was copied.
 */
export async function copyText(text) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* Insecure context or permission denied — try the legacy path. */
  }
  return legacyCopy(text);
}

/**
 * ``document.execCommand("copy")`` fallback for insecure contexts.
 *
 * @param {string} text - Text to place on the clipboard.
 * @returns {boolean} True when the copy command succeeded.
 */
function legacyCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(ta);
  }
}

/**
 * Topic without the ``sberdevices/v1/<login>/`` prefix: ``down/commands``.
 *
 * The login is the same on every row of one bridge's log, so showing it
 * only pushes the part that differs out of view.  Topics outside that
 * shape (``sberdevices/v1/global_config``) keep everything after ``v1/``.
 *
 * @param {string} topic Full MQTT topic.
 * @returns {string} The distinguishing tail of the topic.
 */
export function topicSuffix(topic) {
  const parts = String(topic || "").split("/");
  if (parts.length >= 5 && parts[0] === "sberdevices") return parts.slice(3).join("/");
  if (parts.length >= 3 && parts[0] === "sberdevices") return parts.slice(2).join("/");
  return String(topic || "");
}

/**
 * Filter message-log entries by direction, topic suffix and free text.
 *
 * Every criterion is optional; an empty or missing one matches all.  The
 * text search is case-insensitive over the full topic and the payload, so
 * an entity id or an error code finds the rows that mention it.
 *
 * @param {Array<{direction: string, topic: string, payload: string}>} messages
 * @param {{direction?: string, topic?: string, query?: string}} criteria
 * @returns {Array} Matching entries, order preserved.
 */
export function filterMessages(messages, { direction = "", topic = "", query = "" } = {}) {
  const needle = query.trim().toLowerCase();
  return (messages || []).filter((m) => {
    if (direction && direction !== "all" && m.direction !== direction) return false;
    if (topic && topicSuffix(m.topic) !== topic) return false;
    if (!needle) return true;
    return `${m.topic || ""}\n${m.payload || ""}`.toLowerCase().includes(needle);
  });
}

/**
 * Distinct topic suffixes present in the log, sorted — options for the topic filter.
 *
 * @param {Array<{topic: string}>} messages
 * @returns {string[]}
 */
export function logTopics(messages) {
  return [...new Set((messages || []).map((m) => topicSuffix(m.topic)))].sort();
}

/**
 * Short readable form of a Sber ``value`` object: ``true``, ``500``,
 * ``h=120 s=800 v=600``.  Unknown shapes fall back to JSON so nothing is
 * hidden; ``null`` / ``undefined`` render as an em dash.
 *
 * @param {object|null|undefined} v A ``{"type": ..., "<type>_value": ...}`` object.
 * @returns {string}
 */
export function formatSberValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "object") return String(v);
  const field = {
    BOOL: "bool_value",
    INTEGER: "integer_value",
    FLOAT: "float_value",
    ENUM: "enum_value",
  }[v.type];
  if (field && field in v) return String(v[field]);
  if (v.type === "STRING" && "string_value" in v) return JSON.stringify(v.string_value);
  if (v.type === "COLOUR" && v.colour_value && typeof v.colour_value === "object" && "h" in v.colour_value) {
    const c = v.colour_value;
    return `h=${c.h} s=${c.s} v=${c.v}`;
  }
  return JSON.stringify(v);
}

/**
 * Build a Sber ``value`` object for one feature of the command schema.
 *
 * Numbers are clamped to the feature's bounds; INTEGER goes on the wire as a
 * string, as Sber documents it (``integer_value`` — "long written as a string").
 *
 * @param {{type: string, min?: number, max?: number, components?: object}} feature
 *   An entry of ``sber_mqtt_bridge/command_schema``.
 * @param {*} raw Value from the form: boolean/"true", number or numeric string,
 *   enum string, or ``{h, s, v}`` for colours.
 * @returns {object} ``{"type": ..., "<type>_value": ...}``.
 */
export function makeSberValue(feature, raw) {
  const clamp = (n, low, high) => Math.min(high ?? n, Math.max(low ?? n, n));
  switch (feature.type) {
    case "BOOL":
      return { type: "BOOL", bool_value: raw === true || raw === "true" };
    case "INTEGER":
      return { type: "INTEGER", integer_value: String(Math.round(clamp(Number(raw) || 0, feature.min, feature.max))) };
    case "FLOAT":
      return { type: "FLOAT", float_value: clamp(Number(raw) || 0, feature.min, feature.max) };
    case "COLOUR": {
      const ranges = feature.components || {};
      const part = (name) => {
        const [low, high] = ranges[name] || [];
        return Math.round(clamp(Number(raw?.[name]) || 0, low, high));
      };
      return { type: "COLOUR", colour_value: { h: part("h"), s: part("s"), v: part("v") } };
    }
    case "ENUM":
      return { type: "ENUM", enum_value: String(raw ?? "") };
    default:
      return { type: "STRING", string_value: String(raw ?? "") };
  }
}

/**
 * Wrap states into a ``down/commands`` payload for one entity.
 *
 * @param {string} entityId
 * @param {Array<{key: string, value: object}>} states
 * @returns {string} Pretty-printed JSON, ready for the inject editor.
 */
export function buildCommandPayload(entityId, states) {
  return JSON.stringify({ devices: { [entityId]: { states } } }, null, 2);
}

/**
 * Version of the panel code a page is running, or ``null``.
 *
 * The panel is registered as ``sber-panel.js?v=<integration version>`` and
 * every module inherits that query, so the loaded code carries its version
 * in its own URL.
 *
 * @param {string} moduleUrl ``import.meta.url`` of a panel module.
 * @returns {string|null}
 */
export function loadedPanelVersion(moduleUrl) {
  try {
    return new URL(moduleUrl).searchParams.get("v") || null;
  } catch {
    return null;
  }
}

/**
 * Whether the page still runs panel code of another bridge version.
 *
 * After an upgrade the browser — the Home Assistant app above all — keeps
 * the modules it already loaded: custom elements cannot be redefined, so the
 * new panel cannot replace the old one until the page is reloaded.  The
 * backend reports the version it runs; a mismatch means the code on screen
 * is out of date.
 *
 * @param {string|null} loaded Version from {@link loadedPanelVersion}.
 * @param {string|null|undefined} running Version reported by the backend.
 * @returns {boolean}
 */
export function isPanelStale(loaded, running) {
  return Boolean(loaded && running && loaded !== running);
}
