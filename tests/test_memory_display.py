import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_memory

class TestMemoryDisplay(unittest.TestCase):
    def test_display_expected_table(self):
        b = 1024 ** 3
        output = io.StringIO()
        with patch.object(system_memory, 'physical_memory_bytes', return_value=(15.75*b, 5.23*b)):
            with redirect_stdout(output):
                system_memory.print_ram_status()
        self.assertIn('TotalRAM_GB UsedRAM_GB FreeRAM_GB', output.getvalue())
        self.assertIn('15.75', output.getvalue())
        self.assertIn('10.52', output.getvalue())
        self.assertIn('5.23', output.getvalue())

    def test_unavailable_ram_does_not_crash(self):
        with patch.object(system_memory, 'physical_memory_bytes', return_value=None):
            with redirect_stdout(io.StringIO()) as buf:
                system_memory.print_ram_status()
        self.assertIn('unavailable', buf.getvalue())
