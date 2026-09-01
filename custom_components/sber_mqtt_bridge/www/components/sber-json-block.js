/**
 * Sber MQTT Bridge — collapsible JSON / payload block.
 *
 * Every payload dump in the panel (allowed values, dependencies, raw
 * diagnostic summary, DevTools config/state payloads) used to be a plain
 * ``<div>`` with ``max-height`` + ``overflow-y: auto``.  Desktop browsers draw
 * a scrollbar for that; mobile ones only draw it *while* the finger scrolls, so
 * the block looked like JSON that simply stopped mid-object — missing its
 * closing braces.  A user reported the integration as generating invalid JSON
 * on that basis (issue #44) when the payload was in fact complete.
 *
 * This element makes the clipping explicit and reversible instead:
 *
 * * the collapsed view really contains only :data:`COLLAPSED_LINES` lines —
 *   nothing is hidden behind an invisible scroll area,
 * * an ellipsis line, a fade and a "N more lines hidden" note say so,
 * * "Show all N lines" / "Collapse" is a real ``<button>`` (keyboard operable
 *   for free) carrying ``aria-expanded`` + ``aria-controls``,
 * * "Copy JSON" always copies the *whole* payload, expanded or not, so the
 *   next bug report can be pasted from a phone.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { buttonStyles, codeSurfaceStyles } = await import(`../shared-styles.js${_q}`);
const { copyText } = await import(`../utils.js${_q}`);

/**
 * Lines kept in the collapsed view.
 *
 * Chosen so that the smallest real ``allowed_values`` payload (one feature
 * with an ``integer_values`` range) still fits without a toggle, while the
 * multi-feature ones announce themselves as clipped.
 */
const COLLAPSED_LINES = 14;

/** How long the copy outcome stays on screen before it becomes stale. */
const COPY_FEEDBACK_MS = 2500;

class SberJsonBlock extends LitElement {
  static get properties() {
    return {
      /** Home Assistant object — carries `localize` for the panel strings. */
      hass: { type: Object },
      /** Object (pretty-printed here) or an already formatted string. */
      value: { attribute: false },
      /** Accessible name of the block, e.g. "Allowed Values". */
      label: { type: String },
      /** Shown instead of the block when there is nothing to display. */
      placeholder: { type: String },
      /** Suppress the copy button where the host already provides one. */
      hideCopy: { type: Boolean, attribute: "hide-copy" },
      _expanded: { type: Boolean },
      _copyState: { type: String },
    };
  }

  constructor() {
    super();
    this.value = null;
    this.label = "JSON";
    this.placeholder = "";
    this.hideCopy = false;
    this._expanded = false;
    this._copyState = "";
    this._copyTimer = null;
  }

  /**
   * Full payload as text.
   *
   * @returns {string} Pretty-printed JSON, the string as given, or "".
   */
  get text() {
    const value = this.value;
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      /* Circular structures must not blank the whole dialog. */
      return String(value);
    }
  }

  /**
   * Number of lines in the full payload.
   *
   * @returns {number} Line count (0 for an empty payload).
   */
  get lineCount() {
    const text = this.text;
    return text ? text.split("\n").length : 0;
  }

  /**
   * Whether the payload is long enough to be worth collapsing.
   *
   * @returns {boolean} True when a disclosure control must be offered.
   */
  get isTruncatable() {
    return this.lineCount > COLLAPSED_LINES;
  }

  /**
   * Lines currently withheld from the DOM.
   *
   * @returns {number} 0 when everything is on screen.
   */
  get hiddenLineCount() {
    if (this._expanded || !this.isTruncatable) return 0;
    return this.lineCount - COLLAPSED_LINES;
  }

  /**
   * Text actually rendered — the whole payload unless collapsed.
   *
   * The collapsed form is a real slice, not a CSS crop: what the user cannot
   * see is not sitting in an invisible scroll area either.
   *
   * @returns {string} Rendered text.
   */
  visibleText() {
    const text = this.text;
    if (this._expanded || !this.isTruncatable) return text;
    return `${text.split("\n").slice(0, COLLAPSED_LINES).join("\n")}\n…`;
  }

  /** Toggle between the collapsed slice and the full payload. */
  _toggle() {
    this._expanded = !this._expanded;
  }

  /**
   * Copy the **full** payload, never the collapsed slice.
   *
   * @returns {Promise<void>}
   */
  async _copy() {
    const ok = await copyText(this.text);
    this._setCopyState(ok ? t(this.hass, "json.copied") : t(this.hass, "json.copy_failed"));
  }

  /**
   * Show a transient copy outcome.
   *
   * @param {string} state - Message to announce.
   */
  _setCopyState(state) {
    this._copyState = state;
    if (this._copyTimer) clearTimeout(this._copyTimer);
    /* A result that outlives its cause is a lie about the next attempt. */
    this._copyTimer = setTimeout(() => {
      this._copyTimer = null;
      this._copyState = "";
    }, COPY_FEEDBACK_MS);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._copyTimer) {
      clearTimeout(this._copyTimer);
      this._copyTimer = null;
    }
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  render() {
    if (!this.text) {
      return html`<div class="empty">${this.placeholder || t(this.hass, "json.no_data")}</div>`;
    }
    const hidden = this.hiddenLineCount;
    return html`
      <div class="code-wrap">
        <pre id="code" class="code-surface" role="group" aria-label="${this.label} payload">${this.visibleText()}</pre>
        ${hidden ? html`<div class="fade" aria-hidden="true"></div>` : ""}
      </div>
      <div class="bar">
        ${this.isTruncatable
          ? html`<button
              class="btn btn-secondary"
              aria-expanded=${this._expanded ? "true" : "false"}
              aria-controls="code"
              @click=${this._toggle}
            >${this._expanded ? t(this.hass, "json.collapse") : t(this.hass, "json.expand", { lines: this.lineCount })}</button>`
          : ""}
        ${this.hideCopy
          ? ""
          : html`<button class="btn btn-secondary" @click=${this._copy}>${t(this.hass, "json.copy")}</button>`}
        ${hidden
          ? html`<span class="clip-note">${hidden} more ${hidden === 1 ? "line" : "lines"} hidden</span>`
          : ""}
        <span class="copy-status" role="status" aria-live="polite">${this._copyState}</span>
      </div>
    `;
  }

  static get styles() {
    return [buttonStyles, codeSurfaceStyles, css`
      :host {
        display: block;
      }
      .code-wrap {
        position: relative;
      }
      /* Visible proof that the block continues — the scrollbar mobile
       * browsers refuse to draw.  The gradient ends on the literal
       * .code-surface background from shared-styles.js: a themable colour
       * here would fade the last visible line into a different shade than
       * the surface it sits on.  (No backticks in here: this comment lives
       * inside a css template literal and would end it early.) */
      .fade {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 42px;
        border-radius: 0 0 8px 8px;
        pointer-events: none;
        background: linear-gradient(to bottom, transparent, #1e1e1e);
      }
      .bar {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 6px;
      }
      .btn {
        padding: 4px 12px;
        font-size: 12px;
      }
      .clip-note,
      .copy-status {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .empty {
        font-size: 12px;
        font-style: italic;
        color: var(--secondary-text-color);
      }
    `];
  }
}

customElements.define("sber-json-block", SberJsonBlock);
