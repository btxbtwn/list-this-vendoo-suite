# Vendoo Extension Troubleshooting Guide

## Quick Start (Make sure extension is working)

### 1. Install/Reload Extension
1. Go to `chrome://extensions/`
2. Enable "Developer mode" (toggle top right)
3. Click "Load unpacked" and select the repo's `vendoo-extension/` folder
4. **Important**: After making any code changes, click the refresh icon on the extension card

### 2. Test on Vendoo
1. Open Vendoo and navigate to create a new listing or edit an existing one
2. Open the extension popup (click the extension icon)
3. If you see "⚠ Content script not ready. Please REFRESH the Vendoo page" - **refresh the Vendoo page**
4. After refresh, reopen the popup - you should see "✓ Connected to content script on VENDOO"
5. The popup's **Diagnose Page** button downloads the active page structure and now attempts to capture live dropdown values from the current listing state
6. If the popup closes while diagnostics run, that is expected - the background worker should still finish and trigger the JSON download

### 3. Run Diagnostic Tool
If fields aren't being filled correctly:

1. Open Chrome DevTools (F12) on the Vendoo listing page
2. Copy and paste the entire contents of `vendoo-extension/diagnostic-tool.js` into the console
3. Run these commands:

```javascript
// Check if extension is loaded
vendooDiagnostics.checkExtension()

// Find all input fields on the page
vendooDiagnostics.findAllInputs()

// Find a specific field (e.g., Title)
vendooDiagnostics.findByLabel("Title")

// Test filling a field
vendooDiagnostics.testFill("Title", "Test Product Title")

// See dropdown options for a field
vendooDiagnostics.findDropdownOptions("Condition")

// Export the full page structure
vendooDiagnostics.exportStructure()
```

## Common Issues

### Issue: Extension says "Content script not ready"
**Solution:**
- Refresh the Vendoo page
- Make sure you're on a Vendoo listing page (URL should contain `/item/` or `/listing/`)
- Check that the extension has permission to run on vendoo.co (check `chrome://extensions/`> Details > Site access)

### Issue: Fields not being filled
**Solution:**
1. Open the debug console (extension popup > "Debug Console" section)
2. Look for error messages in red
3. Check Chrome DevTools console (F12) for more detailed `[VENDOO]` logs
4. Run the diagnostic tool to see what selectors are available

### Issue: Dropdowns not working
**Common causes:**
- Dropdown uses React/Material UI with custom components
- Dropdown options load asynchronously
- Dropdown requires specific interaction pattern

**Debugging:**
```javascript
// In DevTools console after running diagnostic tool
vendooDiagnostics.findDropdownOptions("Your Field Name")
```

### Issue: Extension fills wrong fields
**Solution:**
- Vendoo's DOM structure may have changed
- Run `vendooDiagnostics.exportStructure()` and send the output
- Update selectors in `vendoo-extension/content-scripts/vendoo.js`

## How to Find Correct Selectors

### Method 1: Using Chrome DevTools
1. Right-click on the field you want to fill
2. Click "Inspect"
3. Look at the element:
   - Does it have an `id` attribute?
   - Does it have a `name` attribute?
   - What's the label text near it?
   - What classes does it have?

### Method 2: Using the Diagnostic Tool
```javascript
// Find all inputs with their labels
vendooDiagnostics.findAllInputs()

// Then look for your specific field
vendooDiagnostics.findByLabel("Brand")
```

### Method 3: Manual Testing
```javascript
// Test a specific selector
document.querySelector('#your-selector-id')

// Test filling manually
document.querySelector('#your-selector-id').value = "Test Value"
document.querySelector('#your-selector-id').dispatchEvent(new Event('input', { bubbles: true }))
```

## Updating Selectors

Once you've identified the correct selectors, update `vendoo-extension/content-scripts/vendoo.js`:

```javascript
// In findInputByLabel function, add new strategies:

// Strategy 6: Search by custom data attribute
const dataAttrMatch = inputs.find(i => 
    i.offsetParent !== null && 
    i.getAttribute('data-testid') && 
    i.getAttribute('data-testid').includes(labelText.toLowerCase())
);
if (dataAttrMatch) {
    log(`  ✓ Found input via data-testid: "${dataAttrMatch.getAttribute('data-testid')}"`);
    return dataAttrMatch;
}
```

## Testing Changes

1. Make code changes to `vendoo-extension/content-scripts/vendoo.js`
2. Go to `chrome://extensions/`
3. Click refresh icon on the Vendoo extension
4. Hard refresh the Vendoo page (Ctrl+Shift+R or Cmd+Shift+R)
5. Reopen extension popup and test

## Bundle Path Notes

- Generate fresh listing payloads from the top-level `skills/list-this/SKILL.md`.
- Treat `vendoo-extension/skills/list-this/` as a compatibility wrapper only; the top-level `skills/` directory is the source of truth.

## Debug Mode

The extension has a built-in debug status box that appears in the bottom-right corner when filling. Look for:
- **Green text**: Normal operations
- **Orange text**: Warnings (field not found, skipped)
- **Red text**: Errors (fill failed)

## Getting Help

If you're still having issues:

1. **Export page structure:**
   ```javascript
   vendooDiagnostics.exportStructure()
   ```
   Copy the JSON output and save it to a file

2. **Check console logs:**
   - Open Chrome DevTools
   - Go to Console tab
   - Filter by `[VENDOO]` to see extension logs
   - Look for red error messages

3. **Document the issue:**
   - Which field isn't working?
   - What value are you trying to fill?
   - What error messages do you see?
   - Include the page structure export

## JSON Format

Make sure your JSON follows this format:

```json
{
  "title": "Your Product Title",
  "description": "Product description here",
  "price": 45.00,
  "brand": "Brand Name",
  "condition": "Good",
  "primaryColor": "Blue",
  "size": "M",
  "sku": "ITEM-001",
  "tags": ["vintage", "clothing"]
}
```

## Platform-Specific Notes

### Vendoo Main Form
- Uses Material UI components
- Dropdowns require special handling
- Fields may load asynchronously

### eBay Section
- Within Vendoo's eBay section
- May have different field names
- Check `data.ebay_specifics` in your JSON

### Poshmark Section
- Auto-save mode
- Just clicks save after filling main form

### Mercari Section
- Requires shipping selection
- Runs handleMercari() function

### Depop Section
- Has specific field requirements
- Runs handleDepop() function

### Etsy Section
- Complex field requirements
- Runs handleEtsy() function
