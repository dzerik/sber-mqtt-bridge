/**
 * Sber MQTT Bridge — Device table component.
 *
 * Sortable, filterable table of exposed Sber devices with bulk selection,
 * inline delete and category override controls.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
await Promise.all([
  import(`./sber-entity-row.js${_q}`),
  import(`./sber-detail-dialog.js${_q}`),
]);

const { LitElement, html, css } = await import(`../lit-base.js${_q}`);

/** How many times the static category registry is re-fetched after an error. */
const MAX_CATEGORY_ATTEMPTS = 3;

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
      _categories: { type: Array },
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
    this._categories = [];
    this._categoriesLoading = false;
    this._categoryAttempts = 0;
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass) this._loadCategories();
  }

  /**
   * Fetch the Sber category registry once and hand it to every row.
   *
   * The override <select> used to carry a hand-maintained copy of the
   * category list which silently drifted from the backend
   * ``OVERRIDABLE_CATEGORIES``; the registry is now always the server's.
   *
   * ``updated()`` fires on every hass mutation, so a failed fetch is
   * retried a bounded number of times instead of on every state change.
   */
  async _loadCategories() {
    if (
      this._categories.length > 0 ||
      this._categoriesLoading ||
      this._categoryAttempts >= MAX_CATEGORY_ATTEMPTS
    ) {
      return;
    }
    this._categoriesLoading = true;
    this._categoryAttempts += 1;
    try {
      const result = await this.hass.callWS({ type: "sber_mqtt_bridge/list_categories" });
      this._categories = (result.categories || []).map((c) => c.id);
    } catch (e) {
      /* Non-fatal: rows fall back to "auto" + their current category. */
      this._categories = [];
    } finally {
      this._categoriesLoading = false;
    }
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
      th:focus-visible,
      .filter-input:focus-visible,
      input[type="checkbox"]:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: -2px;
      }
      th.not-sortable {
        cursor: default;
      }
      th.not-sortable:hover {
        color: var(--secondary-text-color);
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

  /** ``aria-sort`` value for a sortable column header. */
  _ariaSort(col) {
    if (this._sortCol !== col) return "none";
    return this._sortAsc ? "ascending" : "descending";
  }

  /** Activate a sortable header from the keyboard (Enter/Space). */
  _onSortKeydown(e, col) {
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    e.preventDefault();
    this._onSort(col);
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
            <span class="stat-label" title="Devices the Sber cloud is known to hold. Remembered across restarts.">
              Known to Sber:
            </span>
            <span class="badge badge-green">${extra.cloud_known_count ?? 0}</span>
          </div>
          <div class="counter-item">
            <span
              class="stat-label"
              title="Confirmed since this bridge started. Empty right after a Home Assistant restart — the cloud has no reason to speak up until the app asks for state."
            >
              Confirmed this session:
            </span>
            <span class="badge badge-grey">${extra.acknowledged_count ?? 0}</span>
          </div>
          <div class="counter-item">
            <span
              class="stat-label"
              title="The cloud has never once asked about these. Unlike the counter above, this does not fill up after a restart — a device staying here is the signature of a silent rejection."
            >
              Never confirmed:
            </span>
            <span
              class="badge ${(extra.never_confirmed_count ?? 0) > 0 ? "badge-red" : "badge-grey"}"
            >
              ${extra.never_confirmed_count ?? 0}
            </span>
          </div>
        </div>
        ${(extra.never_confirmed?.length ?? 0) > 0
          ? html`<div class="unack-list">
              Never confirmed by Sber: ${extra.never_confirmed.join(", ")}
            </div>`
          : ""}
      </div>

      <!-- Table card -->
      <div class="card">
        <div class="filter-bar">
          <input
            class="filter-input"
            type="search"
            aria-label="Search devices"
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
                      <th class="not-sortable" style="width:40px">
                        <input
                          type="checkbox"
                          aria-label="Select all devices"
                          .checked=${allSelected}
                          @change=${this._onSelectAll}
                        />
                      </th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("entity_id")}
                        title="Sort by Entity ID"
                        @click=${() => this._onSort("entity_id")}
                        @keydown=${(e) => this._onSortKeydown(e, "entity_id")}
                      >
                        Entity ID
                        <span class="sort-arrow">${this._sortArrow("entity_id")}</span>
                      </th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("name")}
                        title="Sort by Name"
                        @click=${() => this._onSort("name")}
                        @keydown=${(e) => this._onSortKeydown(e, "name")}
                      >
                        Name
                        <span class="sort-arrow">${this._sortArrow("name")}</span>
                      </th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("sber_category")}
                        title="Sort by Category"
                        @click=${() => this._onSort("sber_category")}
                        @keydown=${(e) => this._onSortKeydown(e, "sber_category")}
                      >
                        Category
                        <span class="sort-arrow">${this._sortArrow("sber_category")}</span>
                      </th>
                      <th class="not-sortable">Features</th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("room")}
                        title="Sort by Room"
                        @click=${() => this._onSort("room")}
                        @keydown=${(e) => this._onSortKeydown(e, "room")}
                      >
                        Room
                        <span class="sort-arrow">${this._sortArrow("room")}</span>
                      </th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("state")}
                        title="Sort by State"
                        @click=${() => this._onSort("state")}
                        @keydown=${(e) => this._onSortKeydown(e, "state")}
                      >
                        State
                        <span class="sort-arrow">${this._sortArrow("state")}</span>
                      </th>
                      <th
                        role="columnheader"
                        tabindex="0"
                        aria-sort=${this._ariaSort("is_online")}
                        title="Sort by Online"
                        @click=${() => this._onSort("is_online")}
                        @keydown=${(e) => this._onSortKeydown(e, "is_online")}
                      >
                        Online
                        <span class="sort-arrow">${this._sortArrow("is_online")}</span>
                      </th>
                      <th class="not-sortable">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${filtered.map(
                      (d) => html`
                        <sber-entity-row
                          .device=${d}
                          .categories=${this._categories}
                          .selected=${this._selected.has(d.entity_id)}
                          @selection-changed=${this._onSelectionChanged}
                          @delete-entity=${this._onDeleteEntity}
                          @override-changed=${this._onOverrideChanged}
                          @sync-entity=${this._onSyncEntity}
                          @link-entity=${this._onLinkEntity}
                          @show-detail=${this._onShowDetail}
                        ></sber-entity-row>
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
