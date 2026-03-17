// Quick Test Script - Run this in Chrome DevTools console on a Vendoo listing page
// This tests if the extension's content script is working correctly

(async function testExtension() {
    console.log('%c🧪 Testing Vendoo Extension', 'font-size: 18px; font-weight: bold; color: #4CAF50;');
    
    // Test 1: Check if content script is loaded
    console.log('\n%cTest 1: Content Script Status', 'font-size: 14px; font-weight: bold;');
    const statusBox = document.getElementById('vendoo-debug-box');
    if (statusBox) {
        console.log('✅ Content script is loaded (debug box found)');
    } else {
        console.log('❌ Content script NOT loaded - Refresh the page and reopen the extension popup');
        return;
    }
    
    // Test 2: Test field finding
    console.log('\n%cTest 2: Field Detection', 'font-size: 14px; font-weight: bold;');
    const testFields = ['Title', 'Description', 'Brand', 'Condition', 'Price'];
    
    for (const fieldName of testFields) {
        // Try to find the field using similar logic to the extension
        const labels = Array.from(document.querySelectorAll('label, div[class*="Label"], span[class*="Label"], p, h4, h5, h6'));
        const targetLabel = labels.find(l => 
            l.offsetParent !== null && 
            l.innerText && 
            l.innerText.toLowerCase().includes(fieldName.toLowerCase())
        );
        
        if (targetLabel) {
            let input = null;
            if (targetLabel.getAttribute('for')) {
                input = document.getElementById(targetLabel.getAttribute('for'));
            }
            if (!input) {
                let container = targetLabel.parentElement;
                for (let i = 0; i < 4; i++) {
                    if (!container) break;
                    input = container.querySelector('input:not([type="hidden"]), textarea, select, [role="combobox"]');
                    if (input) break;
                    container = container.parentElement;
                }
            }
            
            if (input) {
                console.log(`✅ ${fieldName}: Found (Label: "${targetLabel.innerText.trim()}")`);
            } else {
                console.log(`⚠️  ${fieldName}: Label found but no input element`);
            }
        } else {
            console.log(`❌ ${fieldName}: Not found`);
        }
    }
    
    // Test 3: Check for common Vendoo selectors
    console.log('\n%cTest 3: Vendoo-Specific Selectors', 'font-size: 14px; font-weight: bold;');
    const selectors = [
        '#generalDetails\\.title',
        '#generalDetails\\.description', 
        '#generalDetails\\.brand',
        '[data-testid="save-item-button"]',
        '.MuiAutocomplete-input',
        '[role="combobox"]'
    ];
    
    selectors.forEach(selector => {
        const el = document.querySelector(selector);
        if (el) {
            console.log(`✅ ${selector}: Found ${el.tagName}`);
        } else {
            console.log(`❌ ${selector}: Not found`);
        }
    });
    
    // Test 4: Try to fill a test field
    console.log('\n%cTest 4: Test Fill', 'font-size: 14px; font-weight: bold;');
    const titleEl = document.querySelector('#generalDetails\\.title') || 
                    Array.from(document.querySelectorAll('input')).find(i => 
                        i.placeholder?.toLowerCase().includes('title')
                    );
    
    if (titleEl) {
        const originalValue = titleEl.value;
        titleEl.focus();
        titleEl.value = 'TEST - Extension Working';
        titleEl.dispatchEvent(new Event('input', { bubbles: true }));
        titleEl.dispatchEvent(new Event('change', { bubbles: true }));
        
        console.log('✅ Test fill successful - Check the Title field!');
        console.log('   Value changed from:', originalValue || '(empty)');
        console.log('   To:', titleEl.value);
        
        // Restore after 3 seconds
        setTimeout(() => {
            titleEl.value = originalValue;
            titleEl.dispatchEvent(new Event('input', { bubbles: true }));
            console.log('   (Value restored to original)');
        }, 3000);
    } else {
        console.log('❌ Could not find Title field to test fill');
    }
    
    console.log('\n%c📊 Test Complete', 'font-size: 14px; font-weight: bold; color: #2196F3;');
    console.log('If you see many ❌ icons, the selectors need to be updated.');
    console.log('Check TROUBLESHOOTING.md for instructions on finding correct selectors.');
    
})();