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
        self.assertEqual(result["general"], 90000)
