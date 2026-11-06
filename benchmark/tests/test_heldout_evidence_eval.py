"""Unit tests for pinned heldout evidence evaluation and contamination checks."""
import copy
import unittest
from unittest.mock import patch

from benchmark import heldout_evidence_eval as ev

COMMIT = 'a' * 40
REPO = 'example/unseen-repository'


def excerpt(path, rows):
    lines = [f'{n:5d} | {text}' for n, text in rows]
    refs = [f'{path}:{n}' for n, _ in rows]
    return {'path': path, 'content': '\n'.join(lines),
            'source_refs': refs, 'visible_refs': refs}


class HoldoutEvaluationTests(unittest.TestCase):
    @staticmethod
    def fixture():
        label = {'id': 'unseen_001', 'question': 'How are requests retried?',
                 'repo': REPO, 'commit': COMMIT, 'suite': 'unseen',
                 'gold_spans': [
                     {'id': 'E1', 'path': 'src/retry.py', 'start_line': 10,
                      'end_line': 11},
                     {'id': 'E2', 'path': 'src/retry.py', 'start_line': 20,
                      'end_line': 20},
                 ]}
        saved = {'suite': 'unseen',
                 'method': {'frozen_source_commit': COMMIT},
                 'repo': REPO,
                 'cases': [{'id': label['id'], 'question': label['question'],
                            'gold_spans': [{'id': 'E1', 'path': 'src/retry.py'}],
                            'variants': {'hybrid': {'top8_diagnostics': [
                                {'path': 'src/retry.py', 'line_start': 10,
                                 'line_end': 11, 'gold_overlap': 999}
                            ]}},
                            'multiwindow_diagnostics': {'alternates': [
                                {'path': 'src/retry.py', 'start_line': 20,
                                 'end_line': 22, 'new_lines': 9,
                                 'gold_overlap': 111}
                            ]}}]}
        # The synthetic alternate metadata is not source-consistent; the
        # selection functions are mocked and receive only its safe projection.
        return [label], saved

    def test_projection_discards_gold_and_scores_after_selection(self):
        labels, report = self.fixture()
        safe, mapping = ev._validate_inputs(labels, report, [],
                                            repository=REPO, commit=COMMIT)
        self.assertEqual(list(mapping), ['unseen_001'])
        self.assertNotIn('gold_spans', str(safe))
        self.assertNotIn('gold_overlap', str(safe))
        base = [excerpt('src/retry.py', [(10, 'def retry():'),
                                         (11, '    pass')])]
        adapt = [excerpt('src/retry.py', [(20, 'return retry()')])]
        merged = [excerpt('src/retry.py', [(10, 'def retry():'),
                                           (11, '    pass'),
                                           (20, 'return retry()')])]
        with patch.object(ev, 'acquire_prefetch_variants',
                          return_value={'0': {'excerpts': base}}) as acq, \
             patch.object(ev, 'select_evidence',
                          return_value={'excerpts': adapt}) as sel, \
             patch.object(ev, 'merge_evidence',
                          side_effect=[{'excerpts': merged},
                                       {'excerpts': merged}]) as merge:
            rows = ev.evaluate(None, safe, mapping)
        self.assertEqual(acq.call_args.args[1], safe[0])
        self.assertEqual(sel.call_args.args[1], safe[0])
        self.assertEqual(merge.call_count, 2)
        self.assertEqual(rows[0]['modes']['baseline']['gold_any_line_ids'], ['E1'])
        self.assertEqual(rows[0]['modes']['adaptive_1']['gold_any_line_ids'], ['E2'])
        self.assertEqual(rows[0]['modes']['merge_anchored_1']['gold_any_line_ids'], ['E1','E2'])
        self.assertEqual(rows[0]['modes']['merge_anchored_1']['gold_complete_span_ids'], ['E1','E2'])
        self.assertEqual(ev.summarize(rows)['modes']['merge_anchored_1']['gross_losses_vs_baseline'], 0)

    def test_overlap_rejects_known_id_and_normalized_question(self):
        labels, report = self.fixture()
        old = {'id': 'unseen_001', 'repo': REPO, 'question': 'other'}
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            ev._validate_inputs(labels, report, [old], repository=REPO, commit=COMMIT)
        old = {'id': 'other', 'repo': REPO, 'question': '  HOW  are requests retried? '}
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            ev._validate_inputs(labels, report, [old], repository=REPO, commit=COMMIT)

    def test_unlabeled_cases_rejected(self):
        labels, report = self.fixture()
        labels[0]['gold_spans'] = []
        with self.assertRaisesRegex(ValueError, 'Missing gold spans'):
            ev._validate_inputs(labels, report, [], repository=REPO, commit=COMMIT)

    def test_report_commit_must_match(self):
        labels, report = self.fixture()
        report['method']['frozen_source_commit'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'pinned'):
            ev._validate_inputs(labels, report, [], repository=REPO, commit=COMMIT)

    def test_invalid_source_path_and_duplicate_span_rejected(self):
        labels, report = self.fixture()
        labels[0]['gold_spans'][0]['path'] = '../private.py'
        with self.assertRaisesRegex(ValueError, 'Noncanonical'):
            ev._validate_inputs(labels, report, [], repository=REPO, commit=COMMIT)
        labels, report = self.fixture()
        labels[0]['gold_spans'][1]['id'] = 'E1'
        with self.assertRaisesRegex(ValueError, 'Duplicate gold span'):
            ev._validate_inputs(labels, report, [], repository=REPO, commit=COMMIT)

    def test_all_source_metrics_check_budget_and_refs(self):
        out = ev._source_metrics([excerpt('src/test.py', [
            (1,'def foo():'),(2,'  pass'),(7,'return True')])])
        self.assertEqual(out['displayed_source_lines'], 3)
        self.assertEqual(out['isolated_source_lines'], 1)
        self.assertEqual(out['isolation_fraction'], .3333)
        bad = excerpt('src/test.py', [(1, 'pass')])
        bad['source_refs'] = ['src/test.py:99']
        with self.assertRaises(ValueError):
            ev._source_metrics([bad])

    def test_any_line_not_full_span(self):
        labels, report = self.fixture()
        spans = labels[0]['gold_spans']
        only_first = [excerpt('src/retry.py', [(10,'retry')])]
        any_ids, full_ids = ev._score(spans, only_first)
        self.assertEqual(any_ids,['E1'])
        self.assertEqual(full_ids, [])

    def test_duplicate_candidates_rejected(self):
        labels, report = self.fixture()
        report['cases'].append(copy.deepcopy(report['cases'][0]))
        with self.assertRaises(ValueError):
            ev._validate_inputs(labels, report, [], repository=REPO, commit=COMMIT)

    def test_frozen_mode_configuration(self):
        self.assertEqual(ev.BUDGET, 3000)
        self.assertEqual(ev.EXCERPT_LIMIT, 6)
        self.assertEqual(ev.BLOCK_SIZE, 1)
        self.assertEqual(ev.DENSE_ALTERNATES, 1)

    def test_remote_checkout_must_be_pinned(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            with patch.object(ev, '_git', side_effect=[d, 'b'*40]):
                with self.assertRaisesRegex(ValueError, 'HEAD'):
                    ev._validate_checkout(Path(d), REPO, COMMIT)


if __name__ == '__main__':
    unittest.main()
