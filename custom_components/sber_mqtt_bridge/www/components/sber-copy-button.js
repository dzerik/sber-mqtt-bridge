/**
 * Sber MQTT Bridge — compact "copy" button placed in front of a JSON value.
 *
 * Tables show payloads cut to a line (message log, replay list, trace
 * events); the full JSON only lived in a tooltip that phones cannot open.
 * This button sits at the start of such a line and copies the *whole*
 * value, so a payload can go into a bug report from any device.
 *
 * ``value`` may be a string (copied as is) or any JSON-serialisable value
 * (pretty-printed).  The outcome shows on the button for a moment.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { copyText } = await import(`../utils.js${_q}`);

/** How long the ✓ / ✗ outcome stays on the button. */
const FEEDBACK_MS = 1500;

/**
 * Text a value is copied as.
 *
 * @param {*} value String, object or anything JSON-serialisable.
 * @returns {string}
 */
export function copyableText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

class SberCopyButton extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      /** What to copy — a string or a JSON-serialisable value. */
      value: { attribute: false },
      _state: { state: true },
    };
  }

  constructor() {
    super();
    this.value = null;
    this._state = "";
    this._timer = null;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearTimeout(this._timer);
  }

  async _copy(event) {
    /* Rows and headers around the button are often clickable themselves. */
    event.stopPropagation();
    const ok = await copyText(copyableText(this.value));
    this._state = ok ? "ok" : "failed";
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._state = "";
    }, FEEDBACK_MS);
  }

  render() {
    const label = this._state === "ok"
      ? t(this.hass, "json.copied")
      : this._state === "failed" ? t(this.hass, "json.copy_failed") : t(this.hass, "json.copy");
    const icon = this._state === "ok" ? "✓" : this._state === "failed" ? "✗" : "\u{1F4CB}";
    return html`<button type="button" class="copy ${this._state}" title=${label} aria-label=${label}
      @click=${this._copy} @keydown=${(e) => e.stopPropagation()}>${icon}</button>`;
  }

  static get styles() {
    return css`
      :host { display: inline-block; vertical-align: middle; margin-right: 6px; }
      .copy {
        min-width: 26px;
        height: 22px;
        padding: 0 4px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        font-size: 12px;
        line-height: 1;
        cursor: pointer;
      }
      .copy:hover { border-color: var(--primary-color, #03a9f4); }
      .copy:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 1px; }
      .copy.ok { color: var(--success-color, #4caf50); }
      .copy.failed { color: var(--error-color, #f44336); }
    `;
  }
}

customElements.define("sber-copy-button", SberCopyButton);
