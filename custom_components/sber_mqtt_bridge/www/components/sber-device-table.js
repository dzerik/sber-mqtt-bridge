/**
 * Sber MQTT Bridge — Device table component.
 *
 * Sortable, filterable table of exposed Sber devices with bulk selection,
 * inline delete and category override controls.
 */

const _v = new URL(import.meta.url).searchParams.get("v") || "";
const _q = _v ? `?v=${_v}` : "";
await Promise.all([
  import(`./sber-entity-row.js${_q}`),
  import(`./sber-detail-dialog.js${_q}`),
]);

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

class SberDeviceTable extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      devices: { type: Array },
      devicesExtra: { type: Object },
      _filter: { type: String },
      _sortCol: { type: String },
      _sortAsc: { type: Boolean },
      _selected: { type: Object },
    };
  }

  constructor() {
    super();
    this.devices = [];
    this.devicesExtra = {};
    this._filter = "";
    this._sortCol = "entity_id";
    this._sortAsc = true;
    this._selected = new Set();
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .card {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0, 0, 0, 0.1));
        padding: 16px;
        margin-bottom: 16px;
      }
      .counters {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-bottom: 12px;
        font-size: 14px;
      }
      .counter-item {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .stat-label {
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        color: #fff;
      }
      .badge-green {
        background: var(--success-color, #4caf50);
      }
      .badge-red {
        background: var(--error-color, #f44336);
      }
      .badge-grey {
        background: #9e9e9e;
      }
      .unack-list {
        margin-top: 8px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .filter-bar {
        display: flex;
        gap: 8px;
        align-items: center;
        margin-bottom: 12px;
      }
      .filter-input {
        flex: 1;
        max-width: 400px;
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
      .bulk-bar {
        display: flex;
        gap: 8px;
        align-items: center;
        margin-bottom: 8px;
        font-size: 13px;
        color: var(--secondary-text-color);
      }
      .btn-sm {
        padding: 4px 12px;
        border: none;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        background: var(--error-color, #f44336);
        color: #fff;
        transition: opacity 0.15s;
      }
      .btn-sm:hover {
        opacity: 0.85;
      }
      .table-wrapper {
        overflow-x: auto;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      th {
        text-align: left;
        padding: 10px 8px;
        font-weight: 500;
        color: var(--secondary-text-color);
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        white-space: nowrap;
        cursor: pointer;
        user-select: none;
      }
      th:hover {
        color: var(--primary-color);
      }
      th .sort-arrow {
        font-size: 11px;
        margin-left: 4px;
      }
      .empty-state {
        text-align: center;
        padding: 48px 16px;
        color: var(--secondary-text-color);
        font-size: 15px;
      }
      input[type="checkbox"] {
        cursor: pointer;
        width: 16px;
        height: 16px;
      }

      /* ── Mobile: cards instead of table ── */
      @media (max-width: 768px) {
        .card {
          padding: 12px;
        }
        .counters {
          gap: 10px;
          font-size: 13px;
        }
        .filter-input {
          max-width: none;
        }
        .table-wrapper {
          overflow-x: visible;
        }
        table, thead, tbody, tr {
          display: block;
        }
        thead {
          display: none;
        }
      }
    `;
  }

  get _filteredDevices() {
    let list = [...this.devices];

    if (this._filter) {
      const q = this._filter.toLowerCase();
      list = list.filter(
        (d) =>
          (d.entity_id || "").toLowerCase().includes(q) ||
          (d.name || "").toLowerCase().includes(q) ||
          (d.sber_category || "").toLowerCase().includes(q) ||
          (d.room || "").toLowerCase().includes(q)
      );
    }

    const col = this._sortCol;
    const asc = this._sortAsc ? 1 : -1;
    list.sort((a, b) => {
      let va = a[col] ?? "";
      let vb = b[col] ?? "";
      if (typeof va === "boolean") {
        va = va ? 1 : 0;
        vb = vb ? 1 : 0;
      }
      if (typeof va === "string") {
        return va.localeCompare(vb) * asc;
      }
      return (va - vb) * asc;
    });

    return list;
  }

  _onSort(col) {
    if (this._sortCol === col) {
      this._sortAsc = !this._sortAsc;
    } else {
      this._sortCol = col;
      this._sortAsc = true;
    }
    this.requestUpdate();
  }

  _sortArrow(col) {
    if (this._sortCol !== col) return "";
    return this._sortAsc ? "\u25B2" : "\u25BC";
  }

  _onFilterInput(e) {
    this._filter = e.target.value;
  }

  _onSelectAll(e) {
    const checked = e.target.checked;
    if (checked) {
      this._selected = new Set(this._filteredDevices.map((d) => d.entity_id));
    } else {
      this._selected = new Set();
    }
    this.requestUpdate();
  }

  _onSelectionChanged(e) {
    const { entityId, selected } = e.detail;
    const s = new Set(this._selected);
    if (selected) {
      s.add(entityId);
    } else {
      s.delete(entityId);
    }
    this._selected = s;
    this.requestUpdate();
  }

  _onDeleteEntity(e) {
    this.dispatchEvent(
      new CustomEvent("remove-entities", {
        detail: { entityIds: [e.detail.entityId] },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onOverrideChanged(e) {
    this.dispatchEvent(
      new CustomEvent("set-override", {
        detail: { entityId: e.detail.entityId, category: e.detail.category },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onLinkEntity(e) {
    this.dispatchEvent(
      new CustomEvent("link-entity", {
        detail: { entityId: e.detail.entityId },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onSyncEntity(e) {
    this.dispatchEvent(
      new CustomEvent("sync-entity", {
        detail: { entityId: e.detail.entityId },
        bubbles: true,
        composed: true,
      })
    );
  }

  _onBulkDelete() {
    if (this._selected.size === 0) return;
    this.dispatchEvent(
      new CustomEvent("remove-entities", {
        detail: { entityIds: [...this._selected] },
        bubbles: true,
        composed: true,
      })
    );
    this._selected = new Set();
  }

  render() {
    const extra = this.devicesExtra || {};
    const filtered = this._filteredDevices;
    const allSelected =
      filtered.length > 0 && filtered.every((d) => this._selected.has(d.entity_id));

    return html`
      <!-- Counters card -->
      <div class="card">
        <div class="counters">
          <div class="counter-item">
            <span class="stat-label">Total exposed:</span>
            <strong>${extra.total ?? 0}</strong>
          </div>
          <div class="counter-item">
            <span class="stat-label">Acknowledged:</span>
            <span class="badge badge-green">${extra.acknowledged_count ?? 0}</span>
          </div>
          <div class="counter-item">
            <span class="stat-label">Unacknowledged:</span>
            <span
              class="badge ${(extra.unacknowledged_count ?? 0) > 0 ? "badge-red" : "badge-grey"}"
            >
              ${extra.unacknowledged_count ?? 0}
            </span>
          </div>
        </div>
        ${(extra.unacknowledged?.length ?? 0) > 0
          ? html`<div class="unack-list">
              Unacknowledged: ${extra.unacknowledged.join(", ")}
            </div>`
          : ""}
      </div>

      <!-- Table card -->
      <div class="card">
        <div class="filter-bar">
          <input
            class="filter-input"
            type="text"
            placeholder="Search devices..."
            .value=${this._filter}
            @input=${this._onFilterInput}
          />
        </div>

        ${this._selected.size > 0
          ? html`
              <div class="bulk-bar">
                <span>${this._selected.size} selected</span>
                <button class="btn-sm" @click=${this._onBulkDelete}>
                  Delete selected
                </button>
              </div>
            `
          : ""}

        ${filtered.length === 0
          ? html`<div class="empty-state">No exposed devices found</div>`
          : html`
              <div class="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th style="width:40px">
                        <input
                          type="checkbox"
                          .checked=${allSelected}
                          @change=${this._onSelectAll}
                        />
                      </th>
                      <th @click=${() => this._onSort("entity_id")}>
                        Entity ID
                        <span class="sort-arrow">${this._sortArrow("entity_id")}</span>
                      </th>
                      <th @click=${() => this._onSort("name")}>
                        Name
                        <span class="sort-arrow">${this._sortArrow("name")}</span>
                      </th>
                      <th @click=${() => this._onSort("sber_category")}>
                        Category
                        <span class="sort-arrow">${this._sortArrow("sber_category")}</span>
                      </th>
                      <th>Features</th>
                      <th @click=${() => this._onSort("room")}>
                        Room
                        <span class="sort-arrow">${this._sortArrow("room")}</span>
                      </th>
                      <th @click=${() => this._onSort("state")}>
                        State
                        <span class="sort-arrow">${this._sortArrow("state")}</span>
                      </th>
                      <th @click=${() => this._onSort("is_online")}>
                        Online
                        <span class="sort-arrow">${this._sortArrow("is_online")}</span>
                      </th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${filtered.map(
                      (d) => html`
                        <tr class="${d.is_online ? "online" : "offline"}">
                          <sber-entity-row
                            .device=${d}
                            .selected=${this._selected.has(d.entity_id)}
                            @selection-changed=${this._onSelectionChanged}
                            @delete-entity=${this._onDeleteEntity}
                            @override-changed=${this._onOverrideChanged}
                            @sync-entity=${this._onSyncEntity}
                            @link-entity=${this._onLinkEntity}
                            @show-detail=${this._onShowDetail}
                          ></sber-entity-row>
                        </tr>
                      `
                    )}
                  </tbody>
                </table>
              </div>
            `}
      </div>
      <sber-detail-dialog .hass=${this.hass}></sber-detail-dialog>
    `;
  }

  _onShowDetail(e) {
    const entityId = e.detail?.entity_id;
    if (!entityId) return;
    const dialog = this.shadowRoot.querySelector("sber-detail-dialog");
    if (dialog) dialog.show(entityId);
  }
}

customElements.define("sber-device-table", SberDeviceTable);
