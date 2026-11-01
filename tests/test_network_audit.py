import json
import unittest
from unittest.mock import patch

from plugins import network_audit


class NetworkAuditTests(unittest.TestCase):
    def test_status_is_read_only(self):
        result = json.loads(network_audit.run({"operation": "status"}))
        self.assertIn("available", result)
        self.assertIn("nmap_installed", result)

    def test_scan_requires_confirmation(self):
        result = json.loads(network_audit.run({
            "operation": "ports", "target": "192.168.1.0/24", "confirmed": False
        }))
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["message"].lower())

    def test_public_target_is_rejected(self):
        result = json.loads(network_audit.run({
            "operation": "discover", "target": "8.8.8.0/24", "confirmed": True
        }))
        self.assertFalse(result["ok"])
        self.assertIn("private", result["message"].lower())

    def test_scope_size_is_bounded(self):
        result = json.loads(network_audit.run({
            "operation": "ports", "target": "10.0.0.0/16", "confirmed": True
        }))
        self.assertFalse(result["ok"])
        self.assertIn("too large", result["message"].lower())

    def test_windows_is_rejected_for_scan(self):
        with patch("plugins.network_audit.platform.system", return_value="Windows"):
            result = json.loads(network_audit.run({
                "operation": "discover", "target": "192.168.1.0/24", "confirmed": True
            }))
        self.assertFalse(result["ok"])
        self.assertIn("Linux", result["message"])

    def test_unknown_operation_rejected(self):
        result = json.loads(network_audit.run({"operation": "exploit"}))
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
