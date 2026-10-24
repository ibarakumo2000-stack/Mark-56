"""Tests for the local static website builder."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins import static_site_builder as builder


class StaticSiteBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"MARK56_WORKSPACE": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def call_builder(self, **kwargs):
        return json.loads(builder.run(kwargs))

    def test_catalog_is_provider_independent(self):
        result = self.call_builder(operation="catalog")
        self.assertTrue(result["provider_independent"])
        self.assertEqual(result["kinds"], ["business", "church", "landing", "portfolio"])

    def test_preview_creates_no_files(self):
        result = self.call_builder(operation="preview", name="sample", kind="portfolio")
        self.assertTrue(result["ok"])
        self.assertIn("preview_html", result)
        self.assertFalse((self.root / "sample").exists())

    def test_create_requires_confirmation(self):
        result = self.call_builder(operation="create", name="sample")
        self.assertFalse(result["ok"])
        self.assertFalse((self.root / "sample").exists())

    def test_create_writes_static_files(self):
        result = self.call_builder(operation="create", name="sample", kind="business", confirmed=True)
        self.assertTrue(result["ok"])
        for name in ("index.html", "style.css", "app.js", "README.md"):
            self.assertTrue((self.root / "sample" / name).is_file())
        html = (self.root / "sample" / "index.html").read_text()
        self.assertIn('name="viewport"', html)
        self.assertIn('href="style.css"', html)
        self.assertIn('src="app.js"', html)

    def test_html_escapes_user_content(self):
        result = self.call_builder(operation="preview", name="sample", site_title='<script>alert(1)</script>')
        self.assertTrue(result["ok"])
        self.assertNotIn("<script>alert(1)</script>", result["preview_html"])

    def test_existing_destination_never_overwritten(self):
        dest = self.root / "existing"
        dest.mkdir()
        marker = dest / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        result = self.call_builder(operation="create", name="existing", confirmed=True)
        self.assertFalse(result["ok"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_path_like_project_name_rejected(self):
        result = self.call_builder(operation="preview", name="../outside")
        self.assertFalse(result["ok"])

    def test_invalid_email_rejected(self):
        result = self.call_builder(operation="preview", name="sample", email="not-an-email")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
