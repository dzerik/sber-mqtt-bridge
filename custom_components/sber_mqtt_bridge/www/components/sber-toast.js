/**
 * Sber MQTT Bridge -- Toast notification component.
 *
 * Lightweight popup that shows a message for a few seconds and fades out.
 * Supports three visual types: info (blue), success (green), error (red).
 *
 * Usage:
 *   const toast = document.querySelector("sber-toast");
 *   toast.show("Device added", "success");
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);

class SberToast extends LitElement {
  static get properties() {
    return {
      _message: { type: String },
      _type: { type: String },
      _visible: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._message = "";
    this._type = "info";
    this._visible = false;
    this._timer = null;
  }

  /**
   * Display a toast notification.
   *
   * @param {string} message - Text to show.
   * @param {"info"|"success"|"error"} [type="info"] - Visual style.
   * @param {number} [duration=3000] - Auto-hide delay in milliseconds.
   */
  show(message, type = "info", duration = 3000) {
    if (this._timer) clearTimeout(this._timer);
    this._message = message;
    this._type = type;
    this._visible = true;
    this._timer = setTimeout(() => {
      this._visible = false;
      this._timer = null;
    }, duration);
  }

  static get styles() {
    return css`
      :host {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 10000;
        pointer-events: none;
      }
      .toast {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 12px 20px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        color: #fff;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
        opacity: 0;
        transform: translateY(16px);
        transition: opacity 0.3s, transform 0.3s;
        pointer-events: auto;
      }
      .toast.visible {
        opacity: 1;
        transform: translateY(0);
      }
      .toast.info {
        background: var(--primary-color, #03a9f4);
      }
      .toast.success {
        background: var(--success-color, #4caf50);
      }
      .toast.error {
        background: var(--error-color, #f44336);
      }
    `;
  }

  render() {
    /* role/aria-live make the toast audible to screen readers; errors are
     * assertive so they interrupt, everything else is polite. */
    return html`
      <div
        class="toast ${this._type} ${this._visible ? "visible" : ""}"
        role=${this._type === "error" ? "alert" : "status"}
        aria-live=${this._type === "error" ? "assertive" : "polite"}
        aria-atomic="true"
      >
        ${this._message}
      </div>
    `;
  }
}

customElements.define("sber-toast", SberToast);
