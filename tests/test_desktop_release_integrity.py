"""Regression tests for desktop release package integrity preflight."""
from __future__ import annotations

import hashlib
import io
import unittest
from unittest.mock import patch

from scripts.verify_desktop_release import (
    download_asset_sha256,
    verify_checksum_manifest,
    verify_metadata,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class DesktopReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.package = b"sample desktop release package bytes"
        self.digest = hashlib.sha256(self.package).hexdigest()
        self.metadata = {
            "version": "56.0.2",
            "target": "linux-x86_64",
            "source_commit": "a" * 40,
            "sha256": self.digest,
            "size": len(self.package),
        }

    def test_download_streams_package_and_computes_sha256_and_size(self):
        with patch(
            "scripts.verify_desktop_release.urllib.request.urlopen",
            return_value=_Response(self.package),
        ):
            digest, size = download_asset_sha256(
                "https://github.com/example/release/download/package.tar.gz"
            )
        self.assertEqual(digest, self.digest)
        self.assertEqual(size, len(self.package))

    def test_package_download_rejects_non_https_url(self):
        with self.assertRaises(SystemExit):
            download_asset_sha256("http://example.invalid/package")

    def test_metadata_must_match_version_target_commit_hash_and_size(self):
        verify_metadata(
            self.metadata,
            version="56.0.2",
            target="linux-x86_64",
            source_commit="a" * 40,
            actual_sha256=self.digest,
            actual_size=len(self.package),
        )

    def test_metadata_rejects_package_hash_mismatch(self):
        with self.assertRaises(SystemExit):
            verify_metadata(
                self.metadata,
                version="56.0.2",
                target="linux-x86_64",
                source_commit="a" * 40,
                actual_sha256="b" * 64,
                actual_size=len(self.package),
            )

    def test_metadata_rejects_wrong_source_commit(self):
        with self.assertRaises(SystemExit):
            verify_metadata(
                self.metadata,
                version="56.0.2",
                target="linux-x86_64",
                source_commit="c" * 40,
                actual_sha256=self.digest,
                actual_size=len(self.package),
            )

    def test_metadata_rejects_size_mismatch(self):
        with self.assertRaises(SystemExit):
            verify_metadata(
                self.metadata,
                version="56.0.2",
                target="linux-x86_64",
                source_commit="a" * 40,
                actual_sha256=self.digest,
                actual_size=len(self.package) + 1,
            )

    def test_checksum_manifest_must_match_package_name_and_actual_digest(self):
        verify_checksum_manifest(
            f"{self.digest}  MARK-LV-Linux-x86_64.tar.gz\n",
            package_name="MARK-LV-Linux-x86_64.tar.gz",
            actual_sha256=self.digest,
        )

    def test_checksum_manifest_rejects_wrong_filename_or_digest(self):
        with self.assertRaises(SystemExit):
            verify_checksum_manifest(
                f"{self.digest}  another-package.tar.gz\n",
                package_name="MARK-LV-Linux-x86_64.tar.gz",
                actual_sha256=self.digest,
            )
        with self.assertRaises(SystemExit):
            verify_checksum_manifest(
                f"{'0' * 64}  MARK-LV-Linux-x86_64.tar.gz\n",
                package_name="MARK-LV-Linux-x86_64.tar.gz",
                actual_sha256=self.digest,
            )

    def test_checksum_manifest_requires_exactly_one_entry(self):
        line = f"{self.digest}  MARK-LV-Linux-x86_64.tar.gz"
        with self.assertRaises(SystemExit):
            verify_checksum_manifest(
                line + "\n" + line,
                package_name="MARK-LV-Linux-x86_64.tar.gz",
                actual_sha256=self.digest,
            )


if __name__ == "__main__":
    unittest.main()
