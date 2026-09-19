from __future__ import annotations

import unittest
from pathlib import Path

from vendoo_studio.services.listing_generate import photo_analysis_usable


class AnalyzePhotosStoresTheReadingTest(unittest.TestCase):
    """Re-analysing must change what the next generation reads.

    The route stored "Photo analysis complete. Found: N photos analyzed.",
    which is not an analysis. ``latest_photo_analysis`` skips it and keeps
    finding the previous reading, so listings were generated from photos that
    had since been read again — including after the vision prompt started
    asking for the department, which is how a women's tee kept coming out as
    menswear even once the model was reporting it correctly.
    """

    def route_source(self) -> str:
        source = (
            Path(__file__).resolve().parents[1] / "vendoo_studio" / "routes" / "chat.py"
        ).read_text(encoding="utf-8")
        body = source[source.index("async def analyze_photos("):]
        marker = "\n@router"
        return body[: body.index(marker)] if marker in body else body

    def test_it_stores_the_analysis_not_a_summary(self):
        route = self.route_source()
        self.assertIn("analysis_text", route)
        self.assertNotIn("photos analyzed.", route)

    def test_what_it_stores_is_what_generation_looks_for(self):
        self.assertTrue(
            photo_analysis_usable("Photo analysis:\n- brand: Belle\n- department: Women")
        )
        # The old summary was not, which is why it never replaced anything.
        self.assertFalse(photo_analysis_usable("Photo analysis complete. Found: 7 photos analyzed."))


if __name__ == "__main__":
    unittest.main()
