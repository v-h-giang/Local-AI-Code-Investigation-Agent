"""Offline regression tests for extractive evidence acquisition."""
import json
from pathlib import Path
import tempfile
import unittest

from evidence_acquisition import acquire_evidence


class NumberedRepo:
    def __init__(self, root):
        self.root = Path(root)
        self.read_calls = []

    def read_file(self, path, start, end):
        file = (self.root / path).resolve()
        if not file.is_relative_to(self.root.resolve()) or not file.is_file():
            raise ValueError("Invalid source path")
        self.read_calls.append((path, start, end))
        lines = file.read_text(encoding="utf-8").splitlines()
        return "\n".join(f"{i} | {line}" for i, line
                         in enumerate(lines, 1) if start <= i <= end)


class EvidenceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = NumberedRepo(self.root)
        for i in range(8):
            (self.root / f"impl{i}.f90").write_text(
                "module checkpoint\n"
                + "\n".join(f"call noop({n})" for n in range(8))
                + "\nsubroutine restore_checkpoint()\n"
                + "call restore_state()\n"
                + "end subroutine\nend module\n",
                encoding="utf-8")

    def test_multifile_extractive_compression_preserves_real_line_refs(self):
        candidates = [
            {"path": f"impl{i}.f90", "line_start": 1, "line_end": 14}
            for i in range(8)]
        snippets = acquire_evidence(self.repo,candidates,
                                    "where is restore checkpoint",max_chars=3600,limit=6)
        self.assertGreaterEqual(len(snippets),2)
        self.assertLessEqual(len(snippets),6)
        self.assertLessEqual(len(json.dumps(snippets,ensure_ascii=False)),3600)
        self.assertEqual(len(self.repo.read_calls),len(snippets))
        for snippet in snippets:
            lines = snippet["content"].splitlines()
            actual = [f"{snippet['path']}:{line.split(' | ',1)[0]}"
                      for line in lines]
            self.assertEqual(snippet["source_refs"],actual)
            self.assertEqual(snippet["visible_refs"],actual)
            self.assertIn("call restore_state()",snippet["content"])
            self.assertNotIn("gold",str(snippet).lower())

    def test_budget_never_slices_a_source_line_or_creates_a_reference(self):
        (self.root / "huge.f90").write_text(
            "subroutine restore_checkpoint() " + "X"*8000 + "\n"
            "call restore_state()\n",encoding="utf-8")
        snippets = acquire_evidence(
            self.repo,[{"path":"huge.f90","line_start":1,"line_end":2}],
            "restore checkpoint",max_chars=550,limit=1)
        self.assertLessEqual(len(json.dumps(snippets,ensure_ascii=False)),550)
        for snippet in snippets:
            self.assertNotIn("X"*20,snippet["content"])
            self.assertNotIn("huge.f90:1",snippet["source_refs"])
            self.assertTrue(all(line.endswith("call restore_state()")
                                for line in snippet["content"].splitlines()))

    def test_untrusted_paths_and_missing_windows_are_not_read(self):
        entries=[
            {"path":"../evil.f90","line_start":1,"line_end":9},
            {"path":"impl1.f90","line_start":None,"line_end":9},
            {"path":"impl2.f90","line_start":20,"line_end":1},
            {"path":"impl3.f90","line_start":1,"line_end":14},
        ]
        result=acquire_evidence(self.repo,entries,"restore",max_chars=1800,limit=6)
        self.assertEqual([r["path"] for r in result],["impl3.f90"])

    def test_repeated_file_uses_one_window(self):
        result=acquire_evidence(
            self.repo,[{"path":"impl0.f90","line_start":1,"line_end":14},
                       {"path":"impl0.f90","line_start":1,"line_end":14}],
            "restore",max_chars=1800,limit=6)
        self.assertEqual(len(result),1)
        self.assertEqual(len(self.repo.read_calls),1)


if __name__=="__main__":
    unittest.main()
