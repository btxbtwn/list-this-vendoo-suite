// Vendoo's general form shows an "Update All" control next to a field when at
// least one marketplace form has a unique value for that field. Clicking it
// copies the general value onto every marketplace form. Matchers are pure so
// Node tests can load this file without a DOM.
(function (root) {
  'use strict';

  function normalizeLabel(value) {
    return String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function isUpdateAllLabel(value) {
    return normalizeLabel(value) === 'update all';
  }

  function isUpdateAllTestId(value) {
    return /^update[-_]?all(?:[-_]?button)?$/i.test(String(value || '').trim());
  }

  function isArmed(el) {
    if (!el || typeof el.getAttribute !== 'function') return false;
    const pressed = el.getAttribute('aria-pressed')
      || el.getAttribute('aria-checked')
      || el.getAttribute('aria-selected')
      || '';
    return String(pressed).toLowerCase() === 'true';
  }

  function isUpdateAllControl(el) {
    if (!el || el.disabled) return false;
    if (isArmed(el)) return false;
    const get = (name) => (typeof el.getAttribute === 'function' ? el.getAttribute(name) : '') || '';
    if (isUpdateAllTestId(get('data-testid'))) return true;
    if (isUpdateAllLabel(get('aria-label')) || isUpdateAllLabel(get('title'))) return true;
    return isUpdateAllLabel(el.innerText || el.textContent || '');
  }

  function clickableUpdateAllTarget(el) {
    if (!el) return null;
    const target = (typeof el.closest === 'function' && el.closest('button, [role="button"], a')) || el;
    if (!isUpdateAllControl(el) && !isUpdateAllControl(target)) return null;
    if (target.disabled || isArmed(target)) return null;
    return target;
  }

  function selectUpdateAllButtons(nodes) {
    const seen = new Set();
    const out = [];
    for (const el of nodes || []) {
      const target = clickableUpdateAllTarget(el);
      if (!target || seen.has(target)) continue;
      seen.add(target);
      out.push(target);
    }
    return out;
  }

  const api = {
    normalizeLabel,
    isUpdateAllLabel,
    isUpdateAllTestId,
    isArmed,
    isUpdateAllControl,
    clickableUpdateAllTarget,
    selectUpdateAllButtons,
  };
  root.vendooUpdateAllButtons = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
