// Vendoo Diagnostic Tool - Run this in browser console on Vendoo listing page
// This helps identify the correct selectors for form fields

(function() {
    'use strict';
    
    console.log('%c🔍 Vendoo Extension Diagnostic Tool', 'font-size: 16px; font-weight: bold; color: #4CAF50;');
    console.log('Run these commands to inspect the page:\n');
    
    // Helper to find elements by various strategies
    window.vendooDiagnostics = {
        
        // Find input by label text
        findByLabel: function(labelText) {
            const labels = Array.from(document.querySelectorAll('label, div[class*="Label"], span[class*="Label"], p'));
            const matches = labels.filter(l => 
                l.innerText && l.innerText.toLowerCase().includes(labelText.toLowerCase())
            );
            
            console.log(`%cFound ${matches.length} labels matching "${labelText}":`, 'color: #2196F3; font-weight: bold;');
            matches.forEach((label, i) => {
                console.log(`  ${i + 1}.`, label);
                console.log(`     Text: "${label.innerText.trim()}"`);
                console.log(`     Tag: ${label.tagName}`);
                console.log(`     Classes: ${label.className}`);
                
                // Try to find associated input
                let input = null;
                if (label.getAttribute('for')) {
                    input = document.getElementById(label.getAttribute('for'));
                }
                if (!input) {
                    let container = label.parentElement;
                    for (let j = 0; j < 5 && container; j++) {
                        input = container.querySelector('input, textarea, select, [role="combobox"]');
                        if (input) break;
                        container = container.parentElement;
                    }
                }
                if (input) {
                    console.log(`     Associated input:`, input);
                    console.log(`     Input ID: ${input.id}`);
                    console.log(`     Input Name: ${input.name}`);
                    console.log(`     Input Classes: ${input.className}`);
                }
                console.log('');
            });
            return matches;
        },
        
        // Find all inputs on the page
        findAllInputs: function() {
            const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]'));
            console.log(`%cFound ${inputs.length} input elements:`, 'color: #FF9800; font-weight: bold;');
            
            inputs.forEach((input, i) => {
                const label = this.getLabelForInput(input);
                console.log(`${i + 1}. ${input.tagName}${input.type ? ' [' + input.type + ']' : ''}`);
                console.log(`   ID: ${input.id || '(none)'}`);
                console.log(`   Name: ${input.name || '(none)'}`);
                console.log(`   Placeholder: ${input.placeholder || '(none)'}`);
                console.log(`   Classes: ${input.className || '(none)'}`);
                console.log(`   Label: ${label || '(none)'}`);
                console.log(`   Value: ${input.value ? input.value.substring(0, 50) : '(empty)'}`);
                console.log('');
            });
            return inputs;
        },
        
        // Get label text for an input
        getLabelForInput: function(input) {
            // Check for explicit label
            if (input.id) {
                const label = document.querySelector(`label[for="${input.id}"]`);
                if (label) return label.innerText.trim();
            }
            
            // Check parent containers
            let container = input.parentElement;
            for (let i = 0; i < 4 && container; i++) {
                const label = container.querySelector('label, div[class*="Label"], span[class*="Label"]');
                if (label && label !== input) return label.innerText.trim();
                container = container.parentElement;
            }
            
            // Check aria-label
            return input.getAttribute('aria-label') || '';
        },
        
        // Test filling a field
        testFill: function(labelText, value) {
            console.log(`%cTesting fill for "${labelText}" with value "${value}"`, 'color: #9C27B0; font-weight: bold;');
            
            const labels = Array.from(document.querySelectorAll('label, div[class*="Label"], span[class*="Label"], p'));
            const targetLabel = labels.find(l => 
                l.innerText && l.innerText.toLowerCase().includes(labelText.toLowerCase())
            );
            
            if (!targetLabel) {
                console.error(`❌ Label "${labelText}" not found`);
                return false;
            }
            
            console.log('✓ Found label:', targetLabel);
            
            let input = null;
            if (targetLabel.getAttribute('for')) {
                input = document.getElementById(targetLabel.getAttribute('for'));
            }
            
            if (!input) {
                let container = targetLabel.parentElement;
                for (let i = 0; i < 4 && container; i++) {
                    input = container.querySelector('input:not([type="hidden"]), textarea, select, [role="combobox"]');
                    if (input) break;
                    container = container.parentElement;
                }
            }
            
            if (!input) {
                console.error('❌ No input found for this label');
                return false;
            }
            
            console.log('✓ Found input:', input);
            
            // Try to set value
            input.focus();
            input.value = value;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            
            console.log('✓ Value set to:', input.value);
            return true;
        },
        
        // Find dropdown/combobox options
        findDropdownOptions: function(labelText) {
            console.log(`%cFinding dropdown options for "${labelText}"`, 'color: #E91E63; font-weight: bold;');
            
            // First find the dropdown input
            const labels = Array.from(document.querySelectorAll('label, div[class*="Label"], span[class*="Label"], p'));
            const targetLabel = labels.find(l => 
                l.innerText && l.innerText.toLowerCase().includes(labelText.toLowerCase())
            );
            
            if (!targetLabel) {
                console.error('❌ Label not found');
                return;
            }
            
            let dropdown = null;
            let container = targetLabel.parentElement;
            for (let i = 0; i < 4 && container; i++) {
                dropdown = container.querySelector('[role="combobox"], input[readonly], .MuiAutocomplete-input');
                if (dropdown) break;
                container = container.parentElement;
            }
            
            if (!dropdown) {
                console.error('❌ Dropdown element not found');
                return;
            }
            
            console.log('✓ Found dropdown:', dropdown);
            
            // Click to open dropdown
            dropdown.click();
            
            setTimeout(() => {
                const options = document.querySelectorAll('[role="option"], li, .MuiAutocomplete-option');
                console.log(`%cFound ${options.length} options:`, 'color: #4CAF50;');
                options.forEach((opt, i) => {
                    console.log(`  ${i + 1}. "${opt.innerText.trim()}"`);
                });
            }, 1000);
        },
        
        // Check if extension content script is loaded
        checkExtension: function() {
            const statusBox = document.getElementById('vendoo-debug-box');
            if (statusBox) {
                console.log('%c✓ Extension content script is loaded and running', 'color: #4CAF50; font-weight: bold;');
                return true;
            } else {
                console.log('%c✗ Extension content script NOT loaded', 'color: #f44336; font-weight: bold;');
                console.log('Try refreshing the Vendoo page and re-opening the extension popup');
                return false;
            }
        },
        
        // Export current page structure
        exportStructure: function() {
            const structure = {
                url: window.location.href,
                title: document.title,
                timestamp: new Date().toISOString(),
                fields: []
            };
            
            const inputs = document.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]');
            inputs.forEach(input => {
                const label = this.getLabelForInput(input);
                structure.fields.push({
                    tag: input.tagName,
                    type: input.type,
                    id: input.id,
                    name: input.name,
                    placeholder: input.placeholder,
                    classes: input.className,
                    label: label,
                    value: input.value
                });
            });
            
            console.log('%cPage Structure:', 'color: #00BCD4; font-weight: bold;');
            console.log(JSON.stringify(structure, null, 2));
            return structure;
        },
        
        // Get all dropdown options from eBay category specifics
        getAllDropdownOptions: async function() {
            console.log('%c🔍 Extracting all dropdown options...', 'font-size: 14px; font-weight: bold; color: #4CAF50;');
            
            // First, click "Show Optional Fields" if it exists
            const optionalBtn = Array.from(document.querySelectorAll('button, div[role="button"], span[role="button"]')).find(btn => {
                const text = (btn.innerText || '').toLowerCase();
                return text.includes('show optional') && !text.includes('hide');
            });
            
            if (optionalBtn) {
                console.log('Clicking "Show Optional Fields"...');
                optionalBtn.click();
                await new Promise(r => setTimeout(r, 3000)); // Wait longer
            }
            
            // Find all category specific dropdowns (only input elements)
            const dropdowns = Array.from(document.querySelectorAll('input[id^="listings.ebay.categorySpecifics."][type="text"]'));
            console.log(`Found ${dropdowns.length} category specific dropdown fields`);
            
            const results = {};
            
            for (const dropdown of dropdowns) {
                // Extract field name from ID (e.g., "53159_Department" → "Department")
                const idParts = dropdown.id.split('_');
                const fieldName = idParts[idParts.length - 1];
                
                console.log(`\n%cExtracting options for: ${fieldName}`, 'color: #2196F3; font-weight: bold;');
                
                // Scroll into view
                dropdown.scrollIntoView({ block: 'center' });
                await new Promise(r => setTimeout(r, 500));
                
                // Click on the right edge of the input to open dropdown
                const rect = dropdown.getBoundingClientRect();
                const x = rect.right - 15;
                const y = rect.top + (rect.height / 2);
                const clickEvent = new MouseEvent('click', { 
                    view: window, bubbles: true, cancelable: true, 
                    clientX: x, clientY: y 
                });
                dropdown.dispatchEvent(clickEvent);
                
                // Wait for dropdown to load
                await new Promise(r => setTimeout(r, 2500));
                
                // Try multiple selectors for options
                let optionTexts = [];
                let attempts = 0;
                const maxAttempts = 3;
                
                while (optionTexts.length === 0 && attempts < maxAttempts) {
                    attempts++;
                    
                    // Find all possible option containers
                    const portals = document.querySelectorAll('[role="presentation"], .MuiAutocomplete-popper, [role="listbox"], .MuiPaper-root, [class*="menu"], [class*="popover"]');
                    
                    for (const portal of portals) {
                        // Check if it's visible
                        const style = window.getComputedStyle(portal);
                        if (style.display === 'none') continue;
                        
                        // Try multiple option selectors
                        const options = Array.from(portal.querySelectorAll('[role="option"], .MuiAutocomplete-option, li[role="option"], li, .MuiListItem-root'));
                        
                        if (options.length > 0) {
                            optionTexts = options.map(opt => opt.innerText.trim()).filter(text => text && text.length > 0 && text.length < 100);
                            if (optionTexts.length > 0) break;
                        }
                    }
                    
                    if (optionTexts.length === 0) {
                        console.log(`  Attempt ${attempts}/${maxAttempts}: No options found yet, waiting...`);
                        await new Promise(r => setTimeout(r, 1500));
                    }
                }
                
                results[fieldName] = optionTexts;
                
                if (optionTexts.length > 0) {
                    console.log(`  ✓ Found ${optionTexts.length} options:`);
                    optionTexts.slice(0, 10).forEach((text, i) => {
                        console.log(`    ${i + 1}. "${text}"`);
                    });
                    if (optionTexts.length > 10) {
                        console.log(`    ... and ${optionTexts.length - 10} more`);
                    }
                } else {
                    console.log('  ⚠️ No options found (dropdown may be empty or still loading)');
                }
                
                // Close dropdown by pressing Escape
                dropdown.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
                await new Promise(r => setTimeout(r, 800));
            }
            
            console.log('\n%c📊 Complete Dropdown Options Mapping:', 'font-size: 14px; font-weight: bold; color: #00BCD4;');
            console.log(JSON.stringify(results, null, 2));
            
            return results;
        }
    };
    
    // Print usage instructions
    console.log('%c📋 Available Commands:', 'font-size: 14px; font-weight: bold;');
    console.log('');
    console.log('%cvendooDiagnostics.findByLabel("Title")', 'color: #2196F3; font-family: monospace;', '- Find input by label text');
    console.log('%cvendooDiagnostics.findAllInputs()', 'color: #FF9800; font-family: monospace;', '- List all input fields');
    console.log('%cvendooDiagnostics.testFill("Title", "Test Item")', 'color: #9C27B0; font-family: monospace;', '- Test filling a field');
    console.log('%cvendooDiagnostics.findDropdownOptions("Condition")', 'color: #E91E63; font-family: monospace;', '- List dropdown options');
    console.log('%cvendooDiagnostics.getAllDropdownOptions()', 'color: #FF5722; font-family: monospace;', '- EXTRACT ALL dropdown options from eBay (run this!)');
    console.log('%cvendooDiagnostics.checkExtension()', 'color: #4CAF50; font-family: monospace;', '- Check if extension is loaded');
    console.log('%cvendooDiagnostics.exportStructure()', 'color: #00BCD4; font-family: monospace;', '- Export page structure as JSON');
    console.log('');
    console.log('%c💡 Tip: Run vendooDiagnostics.getAllDropdownOptions() on eBay to see all available values!', 'color: #FF5722; font-weight: bold;');
    
})();