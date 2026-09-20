const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  isUpdateAllLabel,
  isUpdateAllTestId,
  isUpdateAllControl,
  clickableUpdateAllTarget,
  selectUpdateAllButtons,
} = require('../content-scripts/update-all-buttons.js');

function el(opts = {}) {
  const attrs = {
    'aria-label': opts.aria || '',
    title: opts.title || '',
    'data-testid': opts.testId || '',
    'aria-pressed': opts.pressed || '',
    'aria-checked': opts.checked || '',
    'aria-selected': opts.selected || '',
  };
  const node = {
    disabled: Boolean(opts.disabled),
    innerText: opts.text || '',
    textContent: opts.text || '',
    getAttribute(name) {
      return attrs[name] || '';
    },
    closest(selector) {
      if (opts.closest === null) return null;
      if (opts.closest) return opts.closest;
      if (String(selector).includes('button')) return node;
      return null;
    },
  };
  return node;
}

test('Update All labels match the Vendoo control text exactly', () => {
  assert.equal(isUpdateAllLabel('Update All'), true);
  assert.equal(isUpdateAllLabel('  UPDATE  ALL  '), true);
  assert.equal(isUpdateAllLabel('Update all'), true);
  assert.equal(isUpdateAllLabel('Reset'), false);
  assert.equal(isUpdateAllLabel('Update all marketplaces now'), false);
  assert.equal(isUpdateAllLabel('Save'), false);
});

test('Update All test ids accept the common Vendoo spellings', () => {
  assert.equal(isUpdateAllTestId('update-all'), true);
  assert.equal(isUpdateAllTestId('updateAll'), true);
  assert.equal(isUpdateAllTestId('update-all-button'), true);
  assert.equal(isUpdateAllTestId('save-item-button'), false);
});

test('Update All controls ignore disabled or already-selected toggles', () => {
  assert.equal(isUpdateAllControl(el({ text: 'Update All' })), true);
  assert.equal(isUpdateAllControl(el({ aria: 'Update All' })), true);
  assert.equal(isUpdateAllControl(el({ testId: 'update-all-button', text: 'Sync' })), true);
  assert.equal(isUpdateAllControl(el({ text: 'Update All', disabled: true })), false);
  assert.equal(isUpdateAllControl(el({ text: 'Update All', pressed: 'true' })), false);
  assert.equal(isUpdateAllControl(el({ text: 'Reset' })), false);
});

test('clickable targets collapse inner text nodes onto the button', () => {
  const button = el({ text: 'Update All' });
  const span = el({ text: 'Update All', closest: button });
  assert.equal(clickableUpdateAllTarget(span), button);
  assert.equal(clickableUpdateAllTarget(button), button);
  assert.equal(clickableUpdateAllTarget(el({ text: 'Reset' })), null);
});

test('selectUpdateAllButtons de-dupes the same button found twice', () => {
  const button = el({ text: 'Update All' });
  const span = el({ text: 'Update All', closest: button });
  const other = el({ text: 'Update All' });
  assert.deepEqual(selectUpdateAllButtons([span, button, other]), [button, other]);
  assert.deepEqual(selectUpdateAllButtons([el({ text: 'Save' })]), []);
});

test('general fill and save click Update All so marketplace forms get the new values', () => {
  const src = fs.readFileSync(path.join(__dirname, '../content-scripts/vendoo.js'), 'utf8');
  assert.match(src, /await pushGeneralUpdatesToMarketplaces\(1500\)/);
  assert.match(src, /await pushGeneralUpdatesToMarketplaces\(800\)/);
  assert.match(src, /function clickUpdateAllButtons/);
});
