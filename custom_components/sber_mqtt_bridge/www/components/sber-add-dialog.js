/**
 * Sber MQTT Bridge — Add entity dialog component.
 *
 * Modal dialog for selecting HA entities to expose to Sber,
 * with search, domain grouping and multi-select.
 */

const _v = new URL(import.meta.url).searchParams.get("v") || "";
const { filterEntities } = await import(`../utils.js${_v ? `?v=${_v}` : ""}`);

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

class SberAddDialog extends LitElement {
  static get properties() {
    return {
      open: { type: Boolean, reflect: true },
      hass: { type: Object },
      _entities: { type: Array },
      _filter: { type: String },
      _selected: { type: Object },
      _loading: { type: Boolean },
      _domainFilter: { type: String },
    };
  }

  constructor() {
    super();
    this.open = false;
    this.hass = null;
    this._entities = [];
    this._filter = "";
    this._selected = new Set();
    this._loading = false;
    this._domainFilter = "";
  }

  static get styles() {
    return css`
      :host {
        display: none;
      }
      :host([open]) {
        display: block;
      }
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
      .dialog {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
        width: 90%;
        max-width: 720px;
        max-height: 80vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .dialog-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .dialog-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }
      .close-btn {
        background: none;
        border: none;
        font-size: 20px;
        cursor: pointer;
        color: var(--secondary-text-color);
        padding: 4px 8px;
        border-radius: 4px;
      }
      .close-btn:hover {
        background: var(--secondary-background-color, #eee);
      }
      .dialog-filters {
        display: flex;
        gap: 8px;
        padding: 12px 20px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        flex-wrap: wrap;
      }
      .filter-input {
        flex: 1;
        min-width: 200px;
        padding: 8px 12px;
        border: 1px solid var(--divider-color, #ccc);
        border-radius: 8px;
        font-size: 13px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        outline: none;
      }
      .filter-input:focus {
        border-color: var(--primary-color);
      }
      select.domain-select {
        padding: 8px 12px;
        border: 1px solid var(--divider-color, #ccc);
        border-radius: 8px;
        font-size: 13px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        cursor: pointer;
      }
      .dialog-body {
        flex: 1;
        overflow-y: auto;
        padding: 0;
      }
      .domain-group {
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .domain-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 20px;
        background: var(--secondary-background-color, #f5f5f5);
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
        cursor: pointer;
        user-select: none;
      }
      .domain-header:hover {
        background: var(--divider-color, #e0e0e0);
      }
      .entity-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 20px 8px 32px;
        font-size: 13px;
        border-bottom: 1px solid var(--divider-color, #f0f0f0);
        cursor: pointer;
      }
      .entity-item:hover {
        background: var(--secondary-background-color, #f9f9f9);
      }
      .entity-item input[type="checkbox"] {
        cursor: pointer;
        width: 16px;
        height: 16px;
        flex-shrink: 0;
      }
      .entity-info {
        flex: 1;
        min-width: 0;
      }
      .entity-id {
        font-family: monospace;
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .entity-name {
        font-size: 13px;
        color: var(--primary-text-color);
      }
      .entity-class {
        font-size: 11px;
        color: var(--secondary-text-color);
        margin-left: 8px;
      }
      .dialog-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 12px 20px;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        flex-wrap: wrap;
      }
      .footer-info {
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .footer-actions {
        display: flex;
        gap: 8px;
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
      .empty-state {
        text-align: center;
        padding: 32px;
        color: var(--secondary-text-color);
        font-size: 14px;
      }
    `;
  }

  async show() {
    this.open = true;
    this._selected = new Set();
    this._filter = "";
    this._domainFilter = "";
    await this._loadAvailable();
  }

  hide() {
    this.open = false;
    this._entities = [];
    this._selected = new Set();
  }

  async _loadAvailable() {
    if (!this.hass) return;
    this._loading = true;
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/available_entities",
      });
      this._entities = result.entities || [];
    } catch (e) {
      this._entities = [];
    } finally {
      this._loading = false;
    }
  }

  get _domains() {
    const doms = new Set();
    for (const e of this._entities) {
      doms.add(e.domain);
    }
    return [...doms].sort();
  }

  get _filteredEntities() {
    let list = this._entities;

    if (this._domainFilter) {
      list = list.filter((e) => e.domain === this._domainFilter);
    }

    if (this._filter) {
      list = filterEntities(list, this._filter);
    }

    return list;
  }

  get _groupedEntities() {
    const groups = {};
    for (const e of this._filteredEntities) {
      if (!groups[e.domain]) {
        groups[e.domain] = [];
      }
      groups[e.domain].push(e);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }

  _toggleEntity(entityId) {
    const s = new Set(this._selected);
    if (s.has(entityId)) {
      s.delete(entityId);
    } else {
      s.add(entityId);
    }
    this._selected = s;
    this.requestUpdate();
  }

  _selectAllInDomain(domain) {
    const s = new Set(this._selected);
    for (const e of this._filteredEntities) {
      if (e.domain === domain) {
        s.add(e.entity_id);
      }
    }
    this._selected = s;
    this.requestUpdate();
  }

  _selectAll() {
    this._selected = new Set(this._filteredEntities.map((e) => e.entity_id));
    this.requestUpdate();
  }

  _addSelected() {
    if (this._selected.size === 0) return;
    this.dispatchEvent(
      new CustomEvent("add-entities", {
        detail: { entityIds: [...this._selected] },
        bubbles: true,
        composed: true,
      })
    );
    this.hide();
  }

  _addAllInDomain(domain) {
    const ids = this._entities
      .filter((e) => e.domain === domain)
      .map((e) => e.entity_id);
    if (ids.length === 0) return;
    this.dispatchEvent(
      new CustomEvent("add-entities", {
        detail: { entityIds: ids },
        bubbles: true,
        composed: true,
      })
    );
    this.hide();
  }

  _addAll() {
    const ids = this._entities.map((e) => e.entity_id);
    if (ids.length === 0) return;
    this.dispatchEvent(
      new CustomEvent("add-entities", {
        detail: { entityIds: ids },
        bubbles: true,
        composed: true,
      })
    );
    this.hide();
  }

  render() {
    if (!this.open) return html``;

    const groups = this._groupedEntities;

    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div class="dialog">
          <div class="dialog-header">
            <h2>Add Devices</h2>
            <button class="close-btn" @click=${this.hide}>\u2715</button>
          </div>

          <div class="dialog-filters">
            <input
              class="filter-input"
              type="text"
              placeholder="Search entities..."
              .value=${this._filter}
              @input=${(e) => { this._filter = e.target.value; }}
            />
            <select
              class="domain-select"
              .value=${this._domainFilter}
              @change=${(e) => { this._domainFilter = e.target.value; }}
            >
              <option value="">All domains</option>
              ${this._domains.map(
                (d) => html`<option value=${d}>${d} (${this._entities.filter((e) => e.domain === d).length})</option>`
              )}
            </select>
          </div>

          <div class="dialog-body">
            ${this._loading
              ? html`<div class="empty-state">Loading...</div>`
              : groups.length === 0
                ? html`<div class="empty-state">No available entities found</div>`
                : groups.map(
                    ([domain, entities]) => html`
                      <div class="domain-group">
                        <div
                          class="domain-header"
                          @click=${() => this._selectAllInDomain(domain)}
                        >
                          <span>${domain} (${entities.length})</span>
                          <span style="font-size:11px;font-weight:400">click to select all</span>
                        </div>
                        ${entities.map(
                          (e) => html`
                            <div
                              class="entity-item"
                              @click=${() => this._toggleEntity(e.entity_id)}
                            >
                              <input
                                type="checkbox"
                                .checked=${this._selected.has(e.entity_id)}
                                @click=${(ev) => ev.stopPropagation()}
                                @change=${() => this._toggleEntity(e.entity_id)}
                              />
                              <div class="entity-info">
                                <div class="entity-name">
                                  ${e.friendly_name || e.entity_id}
                                  ${e.device_class
                                    ? html`<span class="entity-class">(${e.device_class})</span>`
                                    : ""}
                                </div>
                                <div class="entity-id">${e.entity_id}</div>
                              </div>
                            </div>
                          `
                        )}
                      </div>
                    `
                  )}
          </div>

          <div class="dialog-footer">
            <div class="footer-info">
              ${this._selected.size > 0
                ? `${this._selected.size} selected`
                : `${this._filteredEntities.length} available`}
            </div>
            <div class="footer-actions">
              <button class="btn btn-secondary" @click=${this._selectAll}>
                Select All
              </button>
              <button class="btn btn-secondary" @click=${this._addAll}>
                Add ALL
              </button>
              <button
                class="btn btn-primary"
                ?disabled=${this._selected.size === 0}
                @click=${this._addSelected}
              >
                Add Selected (${this._selected.size})
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define("sber-add-dialog", SberAddDialog);
