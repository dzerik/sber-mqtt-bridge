/**
 * Sber MQTT Bridge — Entity Link Dialog.
 *
 * Modal dialog for managing entity links on an existing exposed device.
 * Shows related entities from the same physical device with compatibility info.
 * Fires "links-saved" event when links are updated.
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

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
  }

  async show(entityId) {
    this._reset();
    this._entityId = entityId;
    this.open = true;
    await this._loadCandidates();
  }

  hide() {
    this.open = false;
  }

  async _loadCandidates() {
    if (!this.hass || !this._entityId) return;
    this._loading = true;
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
    } catch {
      this._candidates = [];
    } finally {
      this._loading = false;
    }
  }

  _toggle(entityId) {
    const sel = { ...this._selected };
    if (sel[entityId]) {
      delete sel[entityId];
    } else {
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

  static get styles() {
    return css`
      :host { display: none; }
      :host([open]) { display: block; }

      .overlay {
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.5); z-index: 999;
        display: flex; align-items: center; justify-content: center;
      }
      .dialog {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: 0 8px 32px rgba(0,0,0,0.25);
        width: 92%; max-width: 560px; max-height: 80vh;
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
      .body { flex: 1; overflow-y: auto; padding: 16px 20px; }
      .info {
        font-size: 13px; color: var(--secondary-text-color); margin-bottom: 12px;
      }
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
      .empty { text-align: center; padding: 24px; color: var(--secondary-text-color); font-style: italic; }
      .dialog-footer {
        display: flex; align-items: center; justify-content: flex-end;
        padding: 12px 20px; border-top: 1px solid var(--divider-color, #e0e0e0); gap: 8px;
      }
      .btn {
        padding: 8px 16px; border: none; border-radius: 8px;
        font-size: 13px; font-weight: 500; cursor: pointer;
      }
      .btn-primary { background: var(--primary-color); color: #fff; }
      .btn-primary:hover { opacity: 0.85; }
      .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .btn-secondary { background: var(--secondary-background-color, #eee); color: var(--primary-text-color); }
    `;
  }

  render() {
    if (!this.open) return html``;
    const selectedCount = Object.keys(this._selected).length;

    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div class="dialog">
          <div class="dialog-header">
            <h2>Link Entities</h2>
            <button class="close-btn" @click=${this.hide}>\u2715</button>
          </div>

          <div class="body">
            <div class="info">
              <strong>${this._entityId}</strong> (${this._category})<br/>
              Select related entities to link as features of this device.
            </div>

            ${this._loading ? html`<div class="empty">Loading...</div>`
              : this._candidates.length === 0 ? html`<div class="empty">No related entities found on this device.</div>`
              : this._candidates.map((c) => html`
                <div class="candidate-row ${!c.compatible ? 'incompatible' : ''}">
                  <input
                    type="checkbox"
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
              `)}
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
