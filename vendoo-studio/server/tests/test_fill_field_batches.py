from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class FillFieldBatchHelpersTest(unittest.TestCase):
    def test_leftover_fill_timeout_scales_and_batches_by_marketplace(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("function groupFillFieldBatches")
        end = text.index("function compactVendooValue")
        helpers = text[start:end]
        script = helpers + """
const fields = [];
for (let i = 0; i < 26; i++) fields.push({ marketplace: 'ebay', field: 'e' + i });
fields.push({ marketplace: 'etsy', field: 'Size' });
const batches = groupFillFieldBatches(fields);
const result = {
  batchCount: batches.length,
  batchSizes: batches.map((batch) => batch.length),
  empty: groupFillFieldBatches([]),
  fill25: commandTimeoutMs({ type: 'FILL_FIELDS', fields: Array(25).fill({}) }),
  fill0: commandTimeoutMs({ type: 'FILL_FIELDS', fields: [] }),
  fill80: commandTimeoutMs({ type: 'FILL_FIELDS', fields: Array(80).fill({}) }),
  general: commandTimeoutMs({ type: 'FILL_GENERAL' }),
  marketplace: commandTimeoutMs({ type: 'FILL_MARKETPLACE' }),
  clearGeneral: commandTimeoutMs({ type: 'CLEAR_GENERAL' }),
  saveEbay: saveCommandForMarketplace('ebay'),
  saveEtsy: saveCommandForMarketplace('ETSY'),
  saveGeneral: saveCommandForMarketplace('general'),
  saveUnknown: saveCommandForMarketplace('unknown'),
  saveEmpty: saveCommandForMarketplace(''),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["batchCount"], 3)
        self.assertEqual(result["batchSizes"], [25, 1, 1])
        self.assertEqual(result["empty"], [[]])
        self.assertEqual(result["fill25"], 155000)
        self.assertEqual(result["fill0"], 90000)
        self.assertEqual(result["fill80"], 300000)
        self.assertEqual(result["general"], 180000)
        self.assertEqual(result["marketplace"], 180000)
        self.assertEqual(result["clearGeneral"], 90000)
        self.assertEqual(result["saveEbay"], {"type": "SAVE_MARKETPLACE", "platform": "ebay"})
        self.assertEqual(result["saveEtsy"], {"type": "SAVE_MARKETPLACE", "platform": "etsy"})
        self.assertEqual(result["saveGeneral"], {"type": "SAVE_GENERAL"})
        self.assertEqual(result["saveUnknown"], {"type": "SAVE_GENERAL"})
        self.assertEqual(result["saveEmpty"], {"type": "SAVE_GENERAL"})

    def test_leftover_fill_saves_each_marketplace_before_switching(self) -> None:
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("async function runFillFields")
        end = text.index("function groupFillFieldBatches")
        run_fill = text[start:end]
        loop = run_fill[run_fill.index("for (let i = 0;") :]
        self.assertIn("saveCommandForMarketplace(marketplace)", loop)
        self.assertIn("type: 'FILL_FIELDS'", loop)
        self.assertLess(
            loop.index("type: 'FILL_FIELDS'"),
            loop.index("saveCommandForMarketplace(marketplace)"),
        )
        after_loop = run_fill[run_fill.index("const fillLog") :]
        self.assertNotIn("SAVE_GENERAL", after_loop)
        self.assertNotIn("saveCommandForMarketplace", after_loop)
