/**
 * Self-contained lit 3.x re-export.
 *
 * Раньше компоненты панели получали `LitElement`, `html` и `css` через
 * trick `Object.getPrototypeOf(customElements.get("ha-panel-lovelace"))`.
 * Этот подход зависит от того, был ли к моменту загрузки панели
 * зарегистрирован `ha-panel-lovelace` с активным LitElement-prototype.
 *
 * На современном HA frontend эти символы уже не проксируются через
 * prototype — hack рассыпается в "чистых" установках без дополнительных
 * HACS-карт, которые побочно их гидратируют (issue #32).
 *
 * Теперь: статический vendored bundle `vendor/lit.js` (~16 КБ,
 * self-contained) — работает одинаково у любого пользователя, без
 * зависимости от окружения.
 *
 * Cache-busting: `sber-panel.js` загружается как `sber-panel.js?v=X.Y.Z`
 * и передаёт ту же строку запроса дальше по графу импортов.  Этот модуль
 * замыкает цепочку — он подмешивает свой `?v=` в `vendor/lit.js`, иначе
 * единственный по-настоящему большой файл панели остался бы вне
 * версионирования.  Все потребители обязаны импортировать lit-base
 * динамически с тем же `?v=` (см. `VERSION_QUERY`), иначе в графе
 * появятся два независимых инстанса lit.
 */

/** Own `?v=...` query string (empty when loaded without a version). */
export const VERSION_QUERY = new URL(import.meta.url).search;

const lit = await import(`./vendor/lit.js${VERSION_QUERY}`);

/** Names every consumer of this module relies on. */
const REQUIRED_EXPORTS = [
  "LitElement",
  "html",
  "css",
  "ReactiveElement",
  "CSSResult",
  "unsafeCSS",
  "nothing",
  "noChange",
  "render",
  "svg",
  "mathml",
];

/* A static `export ... from` used to fail at link time, naming the missing
 * symbol.  Destructuring a dynamic import silently yields `undefined`
 * instead, and the first component to load then dies with the useless
 * "class extends value undefined".  Re-create the loud failure. */
const missing = REQUIRED_EXPORTS.filter((name) => lit[name] === undefined);
if (missing.length > 0) {
  throw new Error(`vendor/lit.js is missing expected export(s): ${missing.join(", ")}`);
}

export const {
  LitElement,
  html,
  css,
  ReactiveElement,
  CSSResult,
  unsafeCSS,
  nothing,
  noChange,
  render,
  svg,
  mathml,
} = lit;
