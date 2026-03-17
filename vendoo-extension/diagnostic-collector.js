// Shared diagnostic collector used by the popup and background worker.

async function collectPageDiagnostics() {
  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const dropdownPortalSelector = [
    '[role="presentation"]',
    '.MuiAutocomplete-popper',
    '[role="listbox"]',
    '.react-select__menu',
    '.react-select__menu-list',
    '.MuiPaper-root',
    '[class*="menu"]',
    '[class*="popover"]'
  ].join(', ');
  const dropdownOptionSelector = [
    '[role="option"]',
    '.MuiAutocomplete-option',
    'li[role="option"]',
    '.MuiListItem-root',
    'li'
  ].join(', ');

  const unique = (values) => {
    const seen = new Set();
    const output = [];
    values.forEach((value) => {
      const normalized = normalize(value);
      if (!normalized) return;
      const key = normalized.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      output.push(normalized);
    });
    return output;
  };

  const isVisible = (element) => {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) === 0) {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const shouldIgnoreControl = (element) => {
    if (!element || element.tagName?.toLowerCase() !== 'input') {
      return false;
    }
    const ignoredTypes = new Set(['hidden', 'submit', 'button', 'reset', 'file', 'image']);
    return ignoredTypes.has(String(element.type || '').toLowerCase());
  };

  const isDropdownField = (element) =>
    element.tagName === 'SELECT' ||
    (element.getAttribute && ['combobox', 'listbox', 'menu'].includes(element.getAttribute('role'))) ||
    Boolean(element.getAttribute && element.getAttribute('aria-haspopup'));

  const buildSelector = (element) => {
    if (!element || !element.tagName) return '';
    if (element.id) {
      if (window.CSS && typeof window.CSS.escape === 'function') {
        return `#${window.CSS.escape(element.id)}`;
      }
      return `#${String(element.id).replace(/([ #;?%&,.+*~':"!^$[\]()=>|/@])/g, '\\$1')}`;
    }

    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
      const tagName = current.tagName.toLowerCase();
      let index = 1;
      let sibling = current;
      while (sibling.previousElementSibling) {
        sibling = sibling.previousElementSibling;
        if (sibling.tagName === current.tagName) {
          index += 1;
        }
      }
      parts.unshift(`${tagName}:nth-of-type(${index})`);
      current = current.parentElement;
    }
    parts.unshift('body');
    return parts.join(' > ');
  };

  const getLabelSources = (input) => {
    const labelSources = [];

    if (input.labels) {
      labelSources.push(...Array.from(input.labels).map((label) => label.textContent || ''));
    }
    if (input.getAttribute) {
      labelSources.push(input.getAttribute('aria-label') || '');
    }

    const labelledBy = input.getAttribute ? input.getAttribute('aria-labelledby') : '';
    if (labelledBy) {
      labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .forEach((node) => labelSources.push(node.textContent || ''));
    }

    if (input.id) {
      const directLabel = Array.from(document.querySelectorAll('label[for]')).find(
        (label) => label.getAttribute('for') === input.id
      );
      if (directLabel) {
        labelSources.push(directLabel.textContent || '');
      }
    }

    const parentLabel = input.closest('label');
    if (parentLabel) {
      labelSources.push(parentLabel.textContent || '');
    }

    let container = input.parentElement;
    for (let depth = 0; depth < 4 && container; depth += 1) {
      const nearbyLabel = container.querySelector('label, legend, div[class*="Label"], span[class*="Label"], p');
      if (nearbyLabel && nearbyLabel !== input) {
        labelSources.push(nearbyLabel.textContent || '');
        break;
      }
      container = container.parentElement;
    }

    return unique(labelSources);
  };

  const getSectionPath = (element) => {
    const sections = [];
    let current = element.parentElement;
    while (current && current !== document.body) {
      const heading = current.querySelector('legend, h1, h2, h3, h4, h5, h6');
      const ariaLabel = normalize(current.getAttribute?.('aria-label') || '');
      if (heading && isVisible(heading)) {
        sections.unshift(normalize(heading.textContent || ''));
      } else if (ariaLabel && ariaLabel.length <= 120) {
        sections.unshift(ariaLabel);
      }
      current = current.parentElement;
    }
    return unique(sections);
  };

  const getDropdownTrigger = (element) =>
    element.closest?.('.react-select__control, [class*="MuiAutocomplete-root"], [class*="MuiInputBase-root"], [role="combobox"]') || element;

  const dispatchPointerClick = (target, eventInit) => {
    target.dispatchEvent(new MouseEvent('mousedown', eventInit));
    target.dispatchEvent(new MouseEvent('mouseup', eventInit));
    target.dispatchEvent(new MouseEvent('click', eventInit));
  };

  const clickRightEdge = (element) => {
    const trigger = getDropdownTrigger(element);
    const rect = trigger.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      return false;
    }

    const x = Math.max(rect.left + 4, rect.right - Math.min(15, rect.width / 2));
    const y = rect.top + rect.height / 2;
    const pointTarget = document.elementFromPoint(x, y);
    const target = pointTarget && trigger.contains(pointTarget) ? pointTarget : trigger;
    const eventInit = { view: window, bubbles: true, cancelable: true, clientX: x, clientY: y };

    dispatchPointerClick(target, eventInit);
    if (element !== target && typeof element.focus === 'function') {
      element.focus();
    }
    return true;
  };

  const closeOpenDropdowns = async (element) => {
    const escapeEvent = { key: 'Escape', code: 'Escape', keyCode: 27, which: 27, bubbles: true };
    const targets = Array.from(new Set([
      element,
      element?.ownerDocument?.activeElement,
      document.activeElement,
      document.body
    ].filter(Boolean)));

    targets.forEach((target) => {
      target.dispatchEvent(new KeyboardEvent('keydown', escapeEvent));
      target.dispatchEvent(new KeyboardEvent('keyup', escapeEvent));
    });

    if (document.body) {
      document.body.dispatchEvent(
        new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 1, clientY: 1 })
      );
    }

    await sleep(150);
  };

  const readVisibleDropdownOptions = () => {
    const seenNodes = new Set();
    const optionNodes = [];
    const strictFallbackSelector = '[role="option"], .MuiAutocomplete-option, li[role="option"], .MuiListItem-root';

    const addOptionsFromRoot = (root) => {
      Array.from(root.querySelectorAll(dropdownOptionSelector)).forEach((node) => {
        if (seenNodes.has(node) || !isVisible(node)) return;
        seenNodes.add(node);
        optionNodes.push(node);
      });
    };

    Array.from(document.querySelectorAll(dropdownPortalSelector))
      .filter(isVisible)
      .forEach(addOptionsFromRoot);

    if (optionNodes.length === 0) {
      Array.from(document.querySelectorAll(strictFallbackSelector)).forEach((node) => {
        if (seenNodes.has(node) || !isVisible(node)) return;
        seenNodes.add(node);
        optionNodes.push(node);
      });
    }

    return unique(
      optionNodes
        .map((node) => normalize(node.innerText || node.textContent || ''))
        .filter((text) => {
          const lower = text.toLowerCase();
          return (
            text &&
            text.length <= 120 &&
            lower !== 'select' &&
            !lower.includes('create your description') &&
            !lower.includes('description with ai')
          );
        })
    );
  };

  const expandOptionalSections = async () => {
    const triggerTexts = ['Show Optional Fields', 'Optional Fields', 'Show more', 'More options', 'Advanced'];
    const expandedSections = [];
    const buttons = Array.from(document.querySelectorAll('button, span[role="button"], a, div[role="button"]'));

    for (const button of buttons) {
      if (!isVisible(button)) continue;
      const buttonText = normalize(button.innerText || button.textContent || '');
      if (!buttonText) continue;
      if (!triggerTexts.some((text) => buttonText.toLowerCase().includes(text.toLowerCase()))) continue;
      if (button.getAttribute?.('aria-expanded') === 'true') continue;

      button.scrollIntoView({ block: 'center' });
      button.click();
      expandedSections.push(buttonText);
      await sleep(350);
    }

    return unique(expandedSections);
  };

  const getNativeOptions = (element) =>
    element.tagName === 'SELECT'
      ? unique(
          Array.from(element.options)
            .map((option) => normalize(option.textContent || option.label || option.value || ''))
            .filter(Boolean)
        )
      : [];

  const scrapeLiveDropdownOptions = async (element) => {
    const nativeOptions = getNativeOptions(element);
    if (element.tagName === 'SELECT') {
      return { options: nativeOptions.slice(0, 200), source: 'native-select' };
    }

    if (!isDropdownField(element)) {
      return { options: [], source: 'not-applicable' };
    }

    const disabled =
      Boolean(element.disabled) || (element.getAttribute && element.getAttribute('aria-disabled') === 'true');
    if (disabled) {
      return { options: [], source: 'disabled' };
    }

    let options = [];
    for (let attempt = 0; attempt < 3 && options.length === 0; attempt += 1) {
      clickRightEdge(element);
      await sleep(350 + attempt * 200);
      options = readVisibleDropdownOptions();

      if (options.length === 0 && typeof element.focus === 'function') {
        element.focus();
        element.dispatchEvent(
          new KeyboardEvent('keydown', {
            key: 'ArrowDown',
            code: 'ArrowDown',
            keyCode: 40,
            which: 40,
            bubbles: true
          })
        );
        await sleep(250 + attempt * 150);
        options = readVisibleDropdownOptions();
      }

      await closeOpenDropdowns(element);
    }

    return {
      options: options.slice(0, 200),
      source: options.length > 0 ? 'live-dropdown' : 'unavailable'
    };
  };

  const expandedSections = await expandOptionalSections();
  if (expandedSections.length > 0) {
    await sleep(500);
  }

  const controls = [];
  const seenControls = new Set();
  Array.from(
    document.querySelectorAll(
      'input:not([type="hidden"]), textarea, select, [role="combobox"], [aria-haspopup="listbox"], [aria-haspopup="menu"]'
    )
  ).forEach((element) => {
    if (seenControls.has(element) || !isVisible(element) || shouldIgnoreControl(element)) {
      return;
    }
    seenControls.add(element);
    controls.push(element);
  });

  const fields = [];
  for (const input of controls) {
    const labelSources = getLabelSources(input);
    const optionsMeta = await scrapeLiveDropdownOptions(input);

    fields.push({
      label: normalize(labelSources[0] || ''),
      labelSources,
      sectionPath: getSectionPath(input),
      selector: buildSelector(input),
      tag: input.tagName.toLowerCase(),
      type: input.type || '',
      role: input.getAttribute ? input.getAttribute('role') || '' : '',
      name: input.name || '',
      id: input.id || '',
      placeholder: input.placeholder || '',
      classes: typeof input.className === 'string' ? input.className : '',
      value: normalize(input.value || input.textContent || ''),
      isDropdown: isDropdownField(input),
      optionCount: optionsMeta.options.length,
      options: optionsMeta.options,
      optionsSource: optionsMeta.source
    });
  }

  const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
    .filter(isVisible)
    .map((heading) => normalize(heading.textContent || ''))
    .filter(Boolean);

  const dropdownFields = fields.filter((field) => field.isDropdown);

  return {
    url: window.location.href,
    title: document.title,
    timestamp: new Date().toISOString(),
    fieldCount: fields.length,
    dropdownCount: dropdownFields.length,
    dropdownsWithOptions: dropdownFields.filter((field) => field.optionCount > 0).length,
    liveDropdownsWithOptions: dropdownFields.filter(
      (field) => field.optionsSource === 'live-dropdown' && field.optionCount > 0
    ).length,
    totalDropdownOptions: dropdownFields.reduce((sum, field) => sum + field.optionCount, 0),
    expandedSections,
    headings,
    fields
  };
}
