/**
 * Sber MQTT Bridge — Toolbar component.
 *
 * Action bar with Refresh, Re-publish, Add Devices, Bulk Actions
 * and a live connection status indicator.
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

class SberToolbar extends LitElement {
  static get properties() {
    return {
      connected: { type: Boolean },
      totalDevices: { type: Number },
      acknowledgedCount: { type: Number },
      loading: { type: Boolean },
      _bulkOpen: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.connected = false;
    this.totalDevices = 0;
    this.acknowledgedCount = 0;
    this.loading = false;
    this._bulkOpen = false;
  }

  static get styles() {
    return css`
      :host {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s;
      }
      .btn-primary {
        background: var(--primary-color);
        color: #fff;
      }
      .btn-primary:hover {
        opacity: 0.85;
      }
      .btn-primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .btn-secondary {
        background: var(--secondary-background-color, #eee);
        color: var(--primary-text-color);
      }
      .btn-secondary:hover {
        opacity: 0.8;
      }
      .btn-success {
        background: var(--success-color, #4caf50);
        color: #fff;
      }
      .btn-success:hover {
        opacity: 0.85;
      }
      .btn-danger {
        background: var(--error-color, #f44336);
        color: #fff;
      }
      .btn-danger:hover {
        opacity: 0.85;
      }
      .spacer {
        flex: 1;
      }
      .status {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        font-weight: 500;
        color: var(--secondary-text-color);
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
      }
      .dot-green {
        background: var(--success-color, #4caf50);
      }
      .dot-red {
        background: var(--error-color, #f44336);
      }
      .counter {
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .dropdown {
        position: relative;
        display: inline-block;
      }
      .dropdown-menu {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        background: var(--card-background-color, #fff);
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        z-index: 100;
        min-width: 160px;
        overflow: hidden;
      }
      .dropdown-item {
        display: block;
        width: 100%;
        padding: 10px 16px;
        border: none;
        background: none;
        text-align: left;
        font-size: 13px;
        cursor: pointer;
        color: var(--primary-text-color);
        transition: background 0.1s;
      }
      .dropdown-item:hover {
        background: var(--secondary-background-color, #f5f5f5);
      }
      .dropdown-item.danger {
        color: var(--error-color, #f44336);
      }
    `;
  }

  _dispatch(eventName) {
    this.dispatchEvent(
      new CustomEvent(eventName, { bubbles: true, composed: true })
    );
  }

  _toggleBulk() {
    this._bulkOpen = !this._bulkOpen;
  }

  _closeBulk() {
    this._bulkOpen = false;
  }

  _onBulkAddAll() {
    this._closeBulk();
    this._dispatch("toolbar-bulk-add");
  }

  _onClearAll() {
    this._closeBulk();
    if (confirm("Remove ALL exposed entities? This cannot be undone.")) {
      this._dispatch("toolbar-clear-all");
    }
  }

  render() {
    return html`
      <button class="btn btn-secondary" @click=${() => this._dispatch("toolbar-refresh")}>
        \u{21BB} Refresh
      </button>
      <button
        class="btn btn-primary"
        ?disabled=${this.loading}
        @click=${() => this._dispatch("toolbar-republish")}
      >
        ${this.loading ? "Publishing..." : "\u{1F4E4} Re-publish config"}
      </button>
      <button class="btn btn-success" @click=${() => this._dispatch("toolbar-add")}>
        \u{2795} Add Devices
      </button>

      <div class="dropdown">
        <button class="btn btn-secondary" @click=${this._toggleBulk}>
          Bulk \u25BE
        </button>
        ${this._bulkOpen
          ? html`
              <div class="dropdown-menu">
                <button class="dropdown-item" @click=${this._onBulkAddAll}>
                  Add All Entities
                </button>
                <button class="dropdown-item danger" @click=${this._onClearAll}>
                  Clear All
                </button>
              </div>
            `
          : ""}
      </div>

      <span class="spacer"></span>

      <span class="counter">
        ${this.totalDevices} devices (${this.acknowledgedCount} acknowledged)
      </span>

      <span class="status">
        <span class="dot ${this.connected ? "dot-green" : "dot-red"}"></span>
        ${this.connected ? "Connected" : "Disconnected"}
      </span>
    `;
  }

  connectedCallback() {
    super.connectedCallback();
    this._outsideClickHandler = (e) => {
      if (this._bulkOpen && !this.shadowRoot.querySelector(".dropdown")?.contains(e.composedPath()[0])) {
        this._bulkOpen = false;
        this.requestUpdate();
      }
    };
    document.addEventListener("click", this._outsideClickHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._outsideClickHandler) {
      document.removeEventListener("click", this._outsideClickHandler);
    }
  }
}

customElements.define("sber-toolbar", SberToolbar);
