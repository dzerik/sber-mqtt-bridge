/**
 * Sber MQTT Bridge — shared CSS building blocks.
 *
 * The dialog chrome (overlay / dialog / header / footer) and the button
 * palette used to be copy-pasted into every component, and the copies had
 * already drifted: the same ``.btn`` was ``padding: 8px 16px`` in one file
 * and ``6px 14px`` in the next, ``:disabled`` was defined for some variants
 * only, and the link dialog had lost the flex/gap rule entirely.
 *
 * Components now compose these ``CSSResult`` objects and only keep their own
 * deltas (dialog width, layout of their body).  Later rules win, so a
 * component-local ``.dialog { max-width: 820px }`` still overrides the base.
 */

const _q = new URL(import.meta.url).search;
const { css } = await import(`./lit-base.js${_q}`);

/** Button palette: ``.btn`` plus the primary/secondary/success/danger variants. */
export const buttonStyles = css`
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
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn:hover:not(:disabled) {
    opacity: 0.85;
  }
  .btn-primary {
    background: var(--primary-color);
    color: #fff;
  }
  .btn-secondary {
    background: var(--secondary-background-color, #eee);
    color: var(--primary-text-color);
  }
  .btn-success {
    background: var(--success-color, #4caf50);
    color: #fff;
  }
  .btn-danger {
    background: var(--error-color, #f44336);
    color: #fff;
  }
  .btn:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }
`;

/** Modal chrome: hidden host, backdrop, dialog box, header, body, footer. */
export const dialogStyles = css`
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
  .dialog-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
    gap: 8px;
  }
  .body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
  }
  .empty-state {
    text-align: center;
    padding: 32px;
    color: var(--secondary-text-color);
    font-size: 14px;
  }
  .close-btn:focus-visible,
  input:focus-visible,
  select:focus-visible,
  textarea:focus-visible,
  .dialog:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }
`;

/** Search/filter text input used above lists and tables. */
export const filterInputStyles = css`
  .filter-input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid var(--divider-color, #ccc);
    border-radius: 8px;
    font-size: 13px;
    background: var(--card-background-color, #fff);
    color: var(--primary-text-color);
    outline: none;
    box-sizing: border-box;
  }
  .filter-input:focus {
    border-color: var(--primary-color);
  }
`;
