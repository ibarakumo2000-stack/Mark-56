import tempfile
import unittest
from pathlib import Path

from core.single_instance import acquire_single_instance_lock


class SingleInstanceLockTests(unittest.TestCase):
    def test_second_instance_cannot_acquire_held_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mark56.lock"
            first = acquire_single_instance_lock(path)
            self.assertIsNotNone(first)
            try:
                second = acquire_single_instance_lock(path)
                self.assertIsNone(second)
            finally:
                first.close()

            third = acquire_single_instance_lock(path)
            self.assertIsNotNone(third)
            third.close()


if __name__ == "__main__":
    unittest.main()
