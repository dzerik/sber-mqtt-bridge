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
