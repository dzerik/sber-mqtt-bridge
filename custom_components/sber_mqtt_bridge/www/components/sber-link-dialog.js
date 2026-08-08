/**
 * Sber MQTT Bridge — Entity Link Dialog.
 *
 * Modal dialog for managing entity links on an existing exposed device.
 * Shows related entities grouped by same-device / other devices with compatibility info.
 * Fires "links-saved" event when links are updated.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { deepActiveElement } = await import(`../utils.js${_q}`);
const { dialogStyles, buttonStyles } = await import(`../shared-styles.js${_q}`);

class SberLinkDialog extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      open: { type: Boolean, reflect: true },
      _entityId: { type: String },
      _category: { type: String },
      _candidates: { type: Array },
      _allowedRoles: { type: Array },
      _selected: { type: Object },
      _loading: { type: Boolean },
      _saving: { type: Boolean },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this.open = false;
    this._reset();
  }

  _reset() {
    this._entityId = "";
    this._category = "";
    this._candidates = [];
    this._allowedRoles = [];
    this._selected = {};
    this._loading = false;
    this._saving = false;
    this._error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    /* Modal keyboard contract: Escape closes. */
    this._escHandler = (e) => {
      if (this.open && e.key === "Escape") {
        e.stopPropagation();
        this.hide();
      }
    };
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._escHandler) {
      document.removeEventListener("keydown", this._escHandler);
      this._escHandler = null;
    }
  }

  async show(entityId) {
    this._reset();
    this._entityId = entityId;
    this._returnFocusTo = deepActiveElement();
    this.open = true;
    await this.updateComplete;
    const dialog = this.shadowRoot.querySelector(".dialog");
    if (dialog) dialog.focus();
    await this._loadCandidates();
  }

  hide() {
    this.open = false;
    /* Return focus to the row action that opened the dialog (WCAG 2.4.3). */
    const target = this._returnFocusTo;
    this._returnFocusTo = null;
    if (target && typeof target.focus === "function") target.focus();
  }

  async _loadCandidates() {
    if (!this.hass || !this._entityId) return;
    this._loading = true;
    this._error = "";
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/suggest_links",
        entity_id: this._entityId,
      });
      this._candidates = result.candidates || [];
      this._allowedRoles = result.allowed_roles || [];
      this._category = result.category || "";
      // Pre-select currently linked
      const sel = {};
      for (const c of this._candidates) {
        if (c.currently_linked && c.linked_role) {
          sel[c.entity_id] = true;
        }
      }
      this._selected = sel;
    } catch (e) {
      this._candidates = [];
      this._error = e.message || "Failed to load candidates";
    } finally {
      this._loading = false;
    }
  }

  /**
   * Toggle a link candidate, enforcing one entity per Sber role.
   *
   * ``_save`` maps candidates into ``{role: entity_id}``, so two
   * selections claiming the same role would silently collapse to the
   * last one.  Selecting a candidate therefore unselects the previous
   * holder of its role — the same guard sber-wizard applies.
   */
  _toggle(entityId) {
    const sel = { ...this._selected };
    if (sel[entityId]) {
      delete sel[entityId];
    } else {
      const picked = this._candidates.find((c) => c.entity_id === entityId);
      const role = picked?.suggested_role;
      if (role) {
        for (const other of this._candidates) {
          if (other.entity_id !== entityId && other.suggested_role === role) {
            delete sel[other.entity_id];
          }
        }
      }
      sel[entityId] = true;
    }
    this._selected = sel;
    this.requestUpdate();
  }

  async _save() {
    if (!this.hass) return;
    this._saving = true;
    try {
      const links = {};
      for (const c of this._candidates) {
        if (this._selected[c.entity_id] && c.compatible && c.suggested_role) {
          links[c.suggested_role] = c.entity_id;
        }
      }
      await this.hass.callWS({
        type: "sber_mqtt_bridge/set_entity_links",
        entity_id: this._entityId,
        links,
      });
      this.dispatchEvent(new CustomEvent("links-saved", {
        bubbles: true, composed: true,
        detail: { entity_id: this._entityId, links },
      }));
      this.hide();
    } catch (e) {
      this.dispatchEvent(new CustomEvent("links-error", {
        bubbles: true, composed: true,
        detail: { message: e.message || String(e) },
      }));
    } finally {
      this._saving = false;
    }
  }

  _renderCandidateRow(c) {
    return html`
      <div class="candidate-row ${!c.compatible ? 'incompatible' : ''}">
        <input
          type="checkbox"
          aria-label="Link ${c.friendly_name || c.entity_id}"
          .checked=${!!this._selected[c.entity_id]}
          ?disabled=${!c.compatible}
          @change=${() => this._toggle(c.entity_id)}
        />
        <div class="candidate-info">
          <div class="candidate-name">${c.friendly_name}</div>
          <div class="candidate-id">${c.entity_id}</div>
        </div>
        <span class="role-badge ${c.compatible ? 'compatible' : ''}">${c.suggested_role || c.device_class || "?"}</span>
        ${!c.compatible && c.device_class ? html`<span class="not-supported">not supported</span>` : ""}
      </div>
    `;
  }

  _renderCandidates() {
    if (this._loading) return html`<div class="empty">Loading...</div>`;
    if (this._error) return html`<div class="empty error-text">${this._error}</div>`;
    if (this._candidates.length === 0) return html`<div class="empty">No compatible entities found.</div>`;

    const sameDevice = this._candidates.filter(c => c.same_device);
    const otherDevices = this._candidates.filter(c => !c.same_device);

    return html`
      ${sameDevice.length > 0 ? html`
        <div class="section-label">Same device</div>
        ${sameDevice.map(c => this._renderCandidateRow(c))}
      ` : ""}
      ${otherDevices.length > 0 ? html`
        <div class="section-label">${sameDevice.length > 0 ? "Other devices" : "Available entities"}</div>
        ${otherDevices.map(c => this._renderCandidateRow(c))}
      ` : ""}
    `;
  }

  static get styles() {
    return [dialogStyles, buttonStyles, css`
      .dialog { width: 92%; max-width: 560px; max-height: 80vh; }
      .info {
        font-size: 13px; color: var(--secondary-text-color); margin-bottom: 12px;
      }
      .section-label {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        color: var(--secondary-text-color); margin: 12px 0 4px; letter-spacing: 0.5px;
      }
      .section-label:first-child { margin-top: 0; }
      .candidate-row {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 0; border-bottom: 1px solid var(--divider-color, #f0f0f0);
        font-size: 13px;
      }
      .candidate-row.incompatible { opacity: 0.4; }
      .candidate-row input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
      .candidate-info { flex: 1; min-width: 0; }
      .candidate-name { color: var(--primary-text-color); }
      .candidate-id { font-family: monospace; font-size: 11px; color: var(--secondary-text-color); }
      .role-badge {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 11px; font-weight: 500;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }
      .role-badge.compatible {
        background: color-mix(in srgb, var(--success-color, #4caf50) 15%, transparent);
        color: var(--success-color, #4caf50);
      }
      .not-supported {
        font-size: 11px; color: var(--error-color, #f44336);
      }
      .error-text { color: var(--error-color, #f44336); }
      .empty { text-align: center; padding: 24px; color: var(--secondary-text-color); font-style: italic; }
      /* Cancel + Save sit together on the right, unlike the wizard's
       * Back/Next split, so the shared footer's spacing is overridden. */
      .dialog-footer { justify-content: flex-end; }
    `];
  }

  render() {
    if (!this.open) return html``;
    const selectedCount = Object.keys(this._selected).length;

    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="link-dialog-title"
          tabindex="-1"
        >
          <div class="dialog-header">
            <h2 id="link-dialog-title">Link Entities</h2>
            <button class="close-btn" aria-label="Close dialog" @click=${this.hide}>\u2715</button>
          </div>

          <div class="body">
            <div class="info">
              <strong>${this._entityId}</strong> (${this._category})<br/>
              Select related entities to link as features of this device.
            </div>

            ${this._renderCandidates()}
          </div>

          <div class="dialog-footer">
            <button class="btn btn-secondary" @click=${this.hide}>Cancel</button>
            <button class="btn btn-primary" ?disabled=${this._saving} @click=${this._save}>
              ${this._saving ? "Saving..." : `Save${selectedCount > 0 ? ` (${selectedCount})` : ""}`}
            </button>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define("sber-link-dialog", SberLinkDialog);
