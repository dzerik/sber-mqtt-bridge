/**
 * Sber MQTT Bridge — Toolbar component.
 *
 * Action bar with Refresh, Re-publish, Add Devices, Bulk Actions
 * and a live connection status indicator.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { buttonStyles } = await import(`../shared-styles.js${_q}`);
const { deepActiveElement } = await import(`../utils.js${_q}`);

class SberToolbar extends LitElement {
  static get properties() {
    return {
      /** Home Assistant object — carries `localize` for the panel strings. */
      hass: { type: Object },
      connected: { type: Boolean },
      /** Destructive action awaiting confirmation, "" when none. */
      _confirming: { type: String },
      phase: { type: String },
      totalDevices: { type: Number },
      acknowledgedCount: { type: Number },
      /** Devices the cloud is known to hold — survives restarts. */
      cloudKnownCount: { type: Number },
      loading: { type: Boolean },
      healthScore: { type: String },
      healthIssues: { type: Array },
      _bulkOpen: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.connected = false;
    this.phase = "disconnected";
    this.totalDevices = 0;
    this.acknowledgedCount = 0;
    this.cloudKnownCount = 0;
    this.loading = false;
    this.healthScore = "healthy";
    this.healthIssues = [];
    this._bulkOpen = false;
    this._confirming = "";
  }

  static get styles() {
    return [buttonStyles, css`
      button:focus-visible,
      input:focus-visible,
      select:focus-visible,
      textarea:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      :host {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      /* In-panel replacement for window.confirm() */
      .overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 999;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .confirm {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
        padding: 20px;
        width: 92%;
        max-width: 420px;
      }
      .confirm h2 {
        margin: 0 0 8px;
        font-size: 18px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .confirm p {
        margin: 0 0 16px;
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .confirm-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
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

      .health-badge {
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
        text-transform: uppercase;
      }
      .health-yellow {
        background: #fff3cd;
        color: #856404;
      }
      .health-red {
        background: #f8d7da;
        color: #721c24;
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
    `];
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

  /**
   * Ask for confirmation in-panel.
   *
   * Native ``confirm()`` is blocking, unstyled, suppressible by the
   * browser ("prevent this page from creating additional dialogs") and
   * unreachable for the panel's own focus management — so destructive
   * actions get a real modal instead.
   */
  _onClearAll() {
    this._closeBulk();
    /* Remember the control that opened the modal so focus can go back
     * there when it closes (WCAG 2.4.3), exactly like the wizard and the
     * link dialog do. */
    this._returnFocusTo = deepActiveElement();
    this._confirming = "clear-all";
  }

  /** Close the modal and hand focus back to whatever opened it. */
  _closeConfirm() {
    this._confirming = "";
    const target = this._returnFocusTo;
    this._returnFocusTo = null;
    if (target && typeof target.focus === "function") target.focus();
  }

  _cancelConfirm() {
    this._closeConfirm();
  }

  _acceptConfirm() {
    this._closeConfirm();
    this._dispatch("toolbar-clear-all");
  }

  /**
   * Keep Tab inside the modal.
   *
   * Without a trap the next Tab lands on the page behind the overlay,
   * where clicks are blocked — the user ends up driving an element they
   * cannot see the focus ring of.
   *
   * @param {KeyboardEvent} e - Keydown on the modal container.
   */
  _onConfirmKeydown(e) {
    if (e.key !== "Tab") return;
    const focusable = [...this.shadowRoot.querySelectorAll(".confirm button")];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = deepActiveElement();
    if (e.shiftKey && (active === first || !focusable.includes(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }

  /**
   * Surface a message through the panel's toast instead of ``alert()``.
   *
   * @param {string} message - Text to show.
   * @param {string} type - Toast kind ("error", "success", "info").
   */
  _toast(message, type) {
    this.dispatchEvent(
      new CustomEvent("toolbar-toast", {
        detail: { message, type },
        bubbles: true,
        composed: true,
      })
    );
  }

  _renderConfirm() {
    if (this._confirming !== "clear-all") return "";
    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this._cancelConfirm(); }}>
        <div
          class="confirm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="toolbar-confirm-title"
          tabindex="-1"
          @keydown=${this._onConfirmKeydown}
        >
          <h2 id="toolbar-confirm-title">${t(this.hass, "toolbar.clear_all_title")}</h2>
          <p>${t(this.hass, "toolbar.clear_all_warning")}</p>
          <div class="confirm-actions">
            <button class="btn btn-secondary" @click=${this._cancelConfirm}>${t(this.hass, "toolbar.cancel")}</button>
            <button class="btn btn-danger" @click=${this._acceptConfirm}>${t(this.hass, "toolbar.clear_all")}</button>
          </div>
        </div>
      </div>
    `;
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
        this._toast(t(this.hass, "toolbar.import_invalid_json"), "error");
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
        \u{2795} ${t(this.hass, "toolbar.add_device")}
      </button>

      <div class="dropdown">
        <button class="btn btn-secondary" @click=${this._toggleBulk}>
          ${t(this.hass, "toolbar.maintenance")} \u25BE
        </button>
        ${this._bulkOpen
          ? html`
              <div class="dropdown-menu">
                <button class="dropdown-item" @click=${this._onAutoLink}>
                  ${t(this.hass, "toolbar.auto_link")}
                </button>
                <button class="dropdown-item danger" @click=${this._onClearAll}>
                  ${t(this.hass, "toolbar.clear_all")}
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
        ${this.loading ? t(this.hass, "toolbar.publishing") : html`\u{1F4E4} ${t(this.hass, "toolbar.republish")}`}
      </button>
      <button class="btn btn-secondary" @click=${() => this._dispatch("toolbar-refresh")}>
        \u{21BB} ${t(this.hass, "toolbar.refresh")}
      </button>

      <div class="divider"></div>

      <!-- Import / Export -->
      <button class="btn btn-secondary" @click=${() => this._dispatch("toolbar-export")}>
        \u{1F4E5} ${t(this.hass, "toolbar.export")}
      </button>
      <button class="btn btn-secondary" @click=${this._triggerImport}>
        \u{1F4E4} ${t(this.hass, "toolbar.import")}
      </button>
      <input
        type="file"
        accept=".json"
        aria-hidden="true"
        tabindex="-1"
        style="display:none"
        @change=${this._onImportFile}
      />

      <span class="spacer"></span>

      <span class="counter">
        ${t(this.hass, "toolbar.device_counter", { total: this.totalDevices, known: this.cloudKnownCount })}
      </span>

      <span class="status">
        <span class="dot ${this._phaseDot}"></span>
        ${this._phaseLabel}
      </span>

      ${this.healthScore !== "healthy" ? html`
        <span class="health-badge ${this.healthScore === "unhealthy" ? "health-red" : "health-yellow"}"
              title="${(this.healthIssues || []).join(", ")}">
          ${this.healthScore === "unhealthy" ? "\u26A0\uFE0F" : "\u26A0"} ${this.healthScore}
        </span>
      ` : ""}

      ${this._renderConfirm()}
    `;
  }

  get _phaseDot() {
    const m = { ready: "dot-green", starting: "dot-yellow", connecting: "dot-yellow", awaiting_ack: "dot-orange", disconnected: "dot-red" };
    return m[this.phase] || "dot-red";
  }

  get _phaseLabel() {
    // Same vocabulary as the status card — one state, one name.
    const known = ["ready", "starting", "connecting", "awaiting_ack", "disconnected"];
    const phase = known.includes(this.phase) ? this.phase : "disconnected";
    return t(this.hass, `phase.${phase}.label`);
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
    this._outsideClickHandler = (e) => {
      if (this._bulkOpen && !this.shadowRoot.querySelector(".dropdown")?.contains(e.composedPath()[0])) {
        this._bulkOpen = false;
        this.requestUpdate();
      }
    };
    document.addEventListener("click", this._outsideClickHandler);
    /* Modal keyboard contract for the confirm dialog: Escape cancels. */
    this._escHandler = (e) => {
      if (this._confirming && e.key === "Escape") {
        e.stopPropagation();
        this._cancelConfirm();
      }
    };
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._outsideClickHandler) {
      document.removeEventListener("click", this._outsideClickHandler);
      this._outsideClickHandler = null;
    }
    if (this._escHandler) {
      document.removeEventListener("keydown", this._escHandler);
      this._escHandler = null;
    }
  }

  updated(changedProps) {
    if (changedProps.has("_confirming") && this._confirming) {
      /* Move focus into the modal so Escape/Tab work and screen readers
       * announce it (WCAG 2.4.3). */
      this.shadowRoot.querySelector(".confirm")?.focus();
    }
  }
}

customElements.define("sber-toolbar", SberToolbar);
