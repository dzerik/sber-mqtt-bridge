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

/**
 * Filter entities by text query (entity_id or friendly_name).
 *
 * @param {Array} entities - List of entity objects with entity_id and friendly_name.
 * @param {string} query - Search query (case-insensitive).
 * @returns {Array} Filtered entities.
 */
export function filterEntities(entities, query) {
  if (!query) return entities;
  const q = query.toLowerCase();
  return entities.filter(
    (e) =>
      (e.entity_id || "").toLowerCase().includes(q) ||
      (e.friendly_name || "").toLowerCase().includes(q)
  );
}

/**
 * Shared CSS string for dialog components.
 * Use with: css`${DIALOG_STYLES_CSS}`
 */
export const DIALOG_STYLES_CSS = `
  .overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.5); z-index: 999;
    display: flex; align-items: center; justify-content: center;
  }
  .dialog {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.25);
    display: flex; flex-direction: column; overflow: hidden;
  }
  .dialog-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; border-bottom: 1px solid var(--divider-color, #e0e0e0);
  }
  .dialog-header h2 { margin: 0; font-size: 18px; font-weight: 500; }
  .close-btn {
    background: none; border: none; font-size: 20px; cursor: pointer;
    color: var(--secondary-text-color); padding: 4px 8px; border-radius: 4px;
  }
  .close-btn:hover { background: var(--secondary-background-color, #eee); }
  .dialog-footer {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px; border-top: 1px solid var(--divider-color, #e0e0e0);
  }
  .body { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 16px; border: none; border-radius: 8px;
    font-size: 13px; font-weight: 500; cursor: pointer; transition: background 0.15s;
  }
  .btn-primary { background: var(--primary-color); color: #fff; }
  .btn-primary:hover { opacity: 0.85; }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-secondary { background: var(--secondary-background-color, #eee); color: var(--primary-text-color); }
  .btn-secondary:hover { opacity: 0.8; }
  .btn-success { background: var(--success-color, #4caf50); color: #fff; }
  .btn-success:hover { opacity: 0.85; }
  .btn-danger { background: var(--error-color, #f44336); color: #fff; }
  .btn-danger:hover { opacity: 0.85; }
  .empty-state { text-align: center; padding: 32px; color: var(--secondary-text-color); font-size: 14px; }
  .filter-input {
    width: 100%; padding: 8px 12px; margin-bottom: 12px;
    border: 1px solid var(--divider-color, #ccc); border-radius: 8px;
    font-size: 13px; background: var(--card-background-color, #fff);
    color: var(--primary-text-color); outline: none; box-sizing: border-box;
  }
  .filter-input:focus { border-color: var(--primary-color); }
`;
