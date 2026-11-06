"""Tests for shared-budget evidence selection with synthetic numbered source."""
import copy
import json
import unittest

from context_budget_selector import select_evidence, _tokens


class DemoRepo:
    def __init__(self):
        self.calls = []
        self.lines = {
            'src/engine.py': [
                ('def rate_limit_retry(): retry rate limited requests'
                 if i in (75, 76, 77) else
                 'def utility_helper(): pass  # config plumbing'
                 if i == 3 else
                 '    pass  # helper implementation')
                for i in range(1, 121)
            ],
        }

    def read_file(self, path, start_line, end_line):
        self.calls.append((path, start_line, end_line))
        if path not in self.lines:
            raise ValueError('Not a source file')
        return '\n'.join(
            f'{i:5d} | {self.lines[path][i-1]}'
            for i in range(start_line, min(end_line, len(self.lines[path])) + 1))


class ContextBudgetSelectorTests(unittest.TestCase):
    @staticmethod
    def saved():
        return {
            'id': 'demo',
            'question': 'Where is rate limit retry implemented?',
            'variants': {'hybrid': {'top8_diagnostics': [
                {'path': 'src/engine.py', 'line_start': 1, 'line_end': 36},
            ]}},
            'multiwindow_diagnostics': {'alternates': [
                {'path': 'src/engine.py', 'start_line': 66, 'end_line': 100,
                 'new_lines': 35},
            ]},
        }

    def test_both_names_of_line_coordinates(self):
        from context_budget_selector import _window
        self.assertEqual(_window({'path':'a','line_start':1,'line_end':99}),('a',1,48))
        self.assertEqual(_window({'path':'a','start_line':4,'end_line':6}),('a',4,6))
        self.assertIsNone(_window({'path':'a','start_line':0,'end_line':3}))

    def test_compound_identifier_tokens(self):
        self.assertTrue({'rate','limit','retry'} <= _tokens('RateLimitRetry'))
        self.assertTrue({'rate','limit','retry'} <= _tokens('rate_limit_retry'))

    def test_equal_budget_and_source_refs(self):
        saved = self.saved()
        repo = DemoRepo()
        results = [select_evidence(repo,saved,max_chars=3000,
                                   max_alternates=n,limit=6) for n in (0,1)]
        self.assertTrue(repo.calls)
        self.assertGreaterEqual(results[1]['candidate_windows_read'],2)
        for result in results:
            self.assertEqual(result['serialized_chars'],
                             len(json.dumps(result['excerpts'],ensure_ascii=False)))
            self.assertLessEqual(result['serialized_chars'],3000)
            self.assertLessEqual(result['selected_excerpts'],6)
            for snippet in result['excerpts']:
                displayed=[f"{snippet['path']}:{int(s.split('|')[0])}"
                           for s in snippet['content'].splitlines()]
                self.assertEqual(displayed,snippet['source_refs'])
                self.assertEqual(displayed,snippet['visible_refs'])

    def test_gold_field_does_not_change_selection(self):
        saved=self.saved()
        original=select_evidence(DemoRepo(),saved,max_alternates=1)
        copy_case=copy.deepcopy(saved)
        copy_case['gold_spans']=[{'path':'src/engine.py',
                                 'start_line':1,'end_line':120}]
        changed=select_evidence(DemoRepo(),copy_case,max_alternates=1)
        self.assertEqual(original,changed)

    def test_bad_alternate_is_rejected(self):
        saved=self.saved()
        saved['multiwindow_diagnostics']['alternates'][0]['path']='src/unlisted.py'
        with self.assertRaises(ValueError):
            select_evidence(DemoRepo(),saved)

    def test_new_lines_must_match_saved_window(self):
        saved=self.saved()
        saved['multiwindow_diagnostics']['alternates'][0]['new_lines']=100
        with self.assertRaises(ValueError):
            select_evidence(DemoRepo(),saved)

    def test_selector_prefers_relevant_second_window_when_one_slot(self):
        selected=select_evidence(DemoRepo(),self.saved(),
                                 max_chars=1200,max_alternates=1,limit=1)
        self.assertEqual(selected['selected_dense_alternates'],1)
        self.assertIn('rate_limit_retry',selected['excerpts'][0]['content'])


if __name__=='__main__':
    unittest.main()
