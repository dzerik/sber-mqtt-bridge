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
      phase: { type: String },
      totalDevices: { type: Number },
      acknowledgedCount: { type: Number },
      loading: { type: Boolean },
      _bulkOpen: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.connected = false;
    this.phase = "disconnected";
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
      .dot-yellow {
        background: #ff9800;
        animation: pulse 1.5s ease-in-out infinite;
      }
      .dot-orange {
        background: #ff5722;
        animation: pulse 2s ease-in-out infinite;
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
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
      .divider {
        width: 1px;
        align-self: stretch;
        background: var(--divider-color, #e0e0e0);
        margin: 4px 4px;
      }

      /* ── Mobile ── */
      @media (max-width: 768px) {
        :host {
          gap: 6px;
        }
        .btn {
          padding: 6px 10px;
          font-size: 12px;
          gap: 4px;
        }
        .divider {
          display: none;
        }
        /* Force counter + status to new line */
        .spacer {
          flex-basis: 100%;
          height: 0;
        }
        .counter, .status {
          font-size: 12px;
        }
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

  _onAutoLink() {
    this._closeBulk();
    this._dispatch("toolbar-auto-link");
  }

  _onClearAll() {
    this._closeBulk();
    if (confirm("Remove ALL exposed entities? This cannot be undone.")) {
      this._dispatch("toolbar-clear-all");
    }
  }

  _triggerImport() {
    this.shadowRoot.querySelector("input[type=file]")?.click();
  }

  _onImportFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const config = JSON.parse(reader.result);
        this.dispatchEvent(
          new CustomEvent("toolbar-import", {
            detail: { config },
            bubbles: true,
            composed: true,
          })
        );
      } catch {
        alert("Invalid JSON file");
      }
    };
    reader.readAsText(file);
    /* Reset so the same file can be re-imported */
    e.target.value = "";
  }

  render() {
    return html`
      <!-- Primary action -->
      <button class="btn btn-success" @click=${() => this._dispatch("toolbar-wizard")}>
        \u{2795} Add device
      </button>

      <div class="dropdown">
        <button class="btn btn-secondary" @click=${this._toggleBulk}>
          Maintenance \u25BE
        </button>
        ${this._bulkOpen
          ? html`
              <div class="dropdown-menu">
                <button class="dropdown-item" @click=${this._onAutoLink}>
                  Auto-Link Sensors
                </button>
                <button class="dropdown-item danger" @click=${this._onClearAll}>
                  Clear All
                </button>
              </div>
            `
          : ""}
      </div>

      <div class="divider"></div>

      <!-- Sync -->
      <button
        class="btn btn-primary"
        ?disabled=${this.loading}
        @click=${() => this._dispatch("toolbar-republish")}
      >
        ${this.loading ? "Publishing..." : "\u{1F4E4} Re-publish"}
      </button>
      <button class="btn btn-secondary" @click=${() => this._dispatch("toolbar-refresh")}>
        \u{21BB} Refresh
      </button>

      <div class="divider"></div>

      <!-- Import / Export -->
      <button class="btn btn-secondary" @click=${() => this._dispatch("toolbar-export")}>
        \u{1F4E5} Export
      </button>
      <button class="btn btn-secondary" @click=${this._triggerImport}>
        \u{1F4E4} Import
      </button>
      <input
        type="file"
        accept=".json"
        style="display:none"
        @change=${this._onImportFile}
      />

      <span class="spacer"></span>

      <span class="counter">
        ${this.totalDevices} devices (${this.acknowledgedCount} acknowledged)
      </span>

      <span class="status">
        <span class="dot ${this._phaseDot}"></span>
        ${this._phaseLabel}
      </span>
    `;
  }

  get _phaseDot() {
    const m = { ready: "dot-green", starting: "dot-yellow", connecting: "dot-yellow", awaiting_ack: "dot-orange", disconnected: "dot-red" };
    return m[this.phase] || "dot-red";
  }

  get _phaseLabel() {
    const m = { ready: "Connected", starting: "Starting...", connecting: "Connecting...", awaiting_ack: "Awaiting Sber...", disconnected: "Disconnected" };
    return m[this.phase] || "Disconnected";
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
