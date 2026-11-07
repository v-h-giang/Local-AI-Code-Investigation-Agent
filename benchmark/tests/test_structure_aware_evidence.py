"""Gold-blind tests for P1.14 contiguous evidence packing."""
import copy
import json
import unittest

from structure_aware_evidence import pack_contiguous_evidence


class FakeRepo:
    def __init__(self, files):
        self.files = files
        self.reads = []

    def read_file(self, path, start_line=1, end_line=120):
        self.reads.append((path, start_line, end_line))
        rows = self.files[path]
        return '\n'.join(f'{n:5d} | {rows[n - 1]}'
                         for n in range(start_line, min(end_line, len(rows)) + 1))


def saved():
    return {
        'id': 'sample', 'question': 'How does the retry handler return errors?',
        'variants': {'hybrid': {'top8_diagnostics': [
            {'path': 'src/retry.py', 'line_start': 1, 'line_end': 27},
            {'path': 'src/other.py', 'line_start': 1, 'line_end': 16},
        ]}},
        'multiwindow_diagnostics': {'alternates': [
            {'path': 'src/retry.py', 'start_line': 28, 'end_line': 40,
             'new_lines': 13}
        ]},
    }


def source():
    return FakeRepo({
        'src/retry.py': [
            ('def retry_handler(request):' if i == 3 else
             '    if retry_allowed(request):' if i == 4 else
             '        return retry_errors(request)' if i == 5 else
             f'    result_{i} = process_item()')
            for i in range(1, 43)],
        'src/other.py': [f'def no_match_{i}(): pass' for i in range(1, 19)],
    })


class StructureAwareEvidenceTests(unittest.TestCase):
    def test_contiguous_source_and_provenance(self):
        repo = source()
        result = pack_contiguous_evidence(repo, saved())
        self.assertGreater(result['selected_source_lines'], 0)
        self.assertLessEqual(result['serialized_chars'], 3000)
        self.assertLessEqual(result['selected_blocks'], 6)
        self.assertEqual(result['serialized_chars'],
                         len(json.dumps(result['excerpts'], ensure_ascii=False)))
        refs = set()
        for excerpt in result['excerpts']:
            ids = excerpt['source_refs']
            self.assertEqual(excerpt['visible_refs'], ids)
            self.assertTrue(refs.isdisjoint(ids))
            refs.update(ids)
            lines = excerpt['content'].splitlines()
            self.assertEqual(len(lines), len(ids))
            nums = [int(line.split('|')[0]) for line in lines]
            self.assertEqual(nums, list(range(nums[0], nums[-1] + 1)))
            self.assertEqual(ids, [f"{excerpt['path']}:{n}" for n in nums])
            for n, text in zip(nums, lines):
                self.assertEqual(text, f'{n:5d} | {repo.files[excerpt["path"]][n - 1]}')

    def test_query_changes_selection_without_gold(self):
        base = saved()
        a = pack_contiguous_evidence(source(), base, max_chars=1300)
        labeled = copy.deepcopy(base)
        labeled['gold_spans'] = [{'id': 'E1', 'path': 'fake', 'start_line': 999}]
        b = pack_contiguous_evidence(source(), labeled, max_chars=1300)
        self.assertEqual(a, b)

    def test_dense_alternate_is_optional(self):
        with_dense = pack_contiguous_evidence(source(), saved(), max_alternates=1)
        no_dense = pack_contiguous_evidence(source(), saved(), max_alternates=0)
        self.assertEqual(with_dense['read_candidate_windows'], 3)
        self.assertEqual(no_dense['read_candidate_windows'], 2)

    def test_dense_novelty_must_match(self):
        obj = saved()
        obj['multiwindow_diagnostics']['alternates'][0]['new_lines'] = 14
        with self.assertRaises(ValueError):
            pack_contiguous_evidence(source(), obj)

    def test_dense_must_stay_in_hybrid_files(self):
        obj = saved()
        obj['multiwindow_diagnostics']['alternates'][0]['path'] = 'src/not_in_hybrid.py'
        with self.assertRaises(ValueError):
            pack_contiguous_evidence(source(), obj)

    def test_source_reads_are_bounded(self):
        repo = source()
        pack_contiguous_evidence(repo, saved())
        self.assertTrue(all(0 <= end - start < 48 for _, start, end in repo.reads))

    def test_rejects_invalid_budget_and_question(self):
        with self.assertRaises(ValueError):
            pack_contiguous_evidence(source(), saved(), max_chars=100)
        obj = saved()
        obj['question'] = ''
        with self.assertRaises(ValueError):
            pack_contiguous_evidence(source(), obj)

    def test_wide_source_lines_can_be_skipped(self):
        repo = FakeRepo({'src/retry.py': ['x' * 500 for _ in range(27)],
                         'src/other.py': ['y' * 500 for _ in range(16)]})
        obj = saved()
        obj['multiwindow_diagnostics']['alternates'] = []
        answer = pack_contiguous_evidence(repo, obj, max_chars=500)
        self.assertEqual(answer['excerpts'], [])
        self.assertLessEqual(answer['serialized_chars'], 500)


if __name__ == '__main__':
    unittest.main()
