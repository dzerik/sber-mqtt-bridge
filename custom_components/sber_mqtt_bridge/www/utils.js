/**
 * Sber MQTT Bridge -- Shared utilities.
 *
 * Provides slugify (cyrillic-aware) and Salut name validation helpers.
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
 * Validate a device name for the Salut voice assistant.
 *
 * Rules: 3-33 characters, only Cyrillic letters, digits and spaces.
 *
 * @param {string} name - Candidate device name.
 * @returns {boolean} True if the name is valid.
 */
export function isValidSalutName(name) {
  return /^[\u0430-\u044F\u0451\u0410-\u042F\u04010-9 ]{3,33}$/.test(name);
}
