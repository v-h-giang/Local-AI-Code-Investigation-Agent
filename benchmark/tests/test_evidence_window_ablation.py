"""P1.6 source-backed evidence prefetch A/B; synthetic in-memory source."""
import unittest

from benchmark.evidence_window_ablation import (
    acquire_prefetch_variants, evaluate_case, analyze, _span_ids_from_refs,
)


class FakeRepo:
    def __init__(self):
        self.reads=[]
        self.text={
            'src/engine.py':[
                f'{i} | ' + (
                    'def rate_limit_retry(): retry service call'
                    if i in (6,75,125) else
                    '    pass  # unrelated safe source line')
                for i in range(1,181)
            ]
        }

    def read_file(self,path,start,end):
        self.reads.append((path,start,end))
        if path not in self.text:
            raise ValueError('Unknown source path')
        return '\n'.join(self.text[path][start-1:end])


class EvidenceWindowAblationTests(unittest.TestCase):
    @staticmethod
    def fixture():
        question='Where does rate limit retry occur?'
        saved={
            'id':'case-1','question':question,
            'variants':{'hybrid':{'top8_diagnostics':[
                {'path':'src/engine.py','line_start':1,'line_end':22}
            ]}},
            'multiwindow_diagnostics':{'alternates':[
                {'path':'src/engine.py','start_line':67,
                 'end_line':88,'new_lines':22},
                {'path':'src/engine.py','start_line':115,
                 'end_line':136,'new_lines':22},
            ]},
        }
        source={'id':'case-1','suite':'repocontextbench','question':question,
                'gold_spans':[
                    {'id':'E1','path':'src/engine.py','start_line':6,'end_line':6},
                    {'id':'E2','path':'src/engine.py','start_line':75,'end_line':75},
                    {'id':'E3','path':'src/engine.py','start_line':125,'end_line':125},
                ]}
        return saved,source

    def test_baseline_uses_existing_acquire_evidence_exactly(self):
        saved,_=self.fixture()
        repo=FakeRepo()
        variants=acquire_prefetch_variants(repo,saved,max_chars=3000,
                                           per_window_chars=500,limit=6)
        from evidence_acquisition import acquire_evidence
        expected=acquire_evidence(
            repo,saved['variants']['hybrid']['top8_diagnostics'],
            saved['question'],max_chars=3000,limit=6,mode='structure_mmr')
        self.assertEqual(variants['0']['excerpts'],expected)
        for level in ('0','1','2'):
            self.assertLessEqual(variants[level]['serialized_chars'],3000)
        self.assertEqual(variants['1']['alternate_windows_requested'],1)
        self.assertEqual(variants['2']['alternate_windows_requested'],2)
        self.assertTrue(variants['2']['alternate_windows_emitted']>=1)

    def test_excerpts_have_only_visible_and_real_line_refs(self):
        saved,source=self.fixture()
        result=evaluate_case(FakeRepo(),saved,source)
        for variant in result['variants'].values():
            self.assertLessEqual(variant['serialized_chars'],3000)
            self.assertLessEqual(variant['gold_spans_citable'],
                                 variant['gold_spans_visible'])
        self.assertGreaterEqual(
            result['variants']['0']['gold_spans_visible'],1)

    def test_direct_ref_scoring_cannot_invent_span(self):
        spans=[{'id':'E1','path':'src/a.f90','start_line':10,'end_line':12}]
        excerpts=[{'visible_refs':['src/a.f90:5'],
                   'source_refs':['src/a.f90:5']}]
        self.assertEqual(_span_ids_from_refs(spans,excerpts,'visible_refs'),[])
        self.assertEqual(_span_ids_from_refs(
            spans,[{'visible_refs':['src/a.f90:10']}],
            'visible_refs'),['E1'])

    def test_disallows_alternate_outside_original_hybrid_files(self):
        saved,_=self.fixture()
        saved['multiwindow_diagnostics']['alternates'][0]['path']='src/other.py'
        with self.assertRaises(ValueError):
            acquire_prefetch_variants(FakeRepo(),saved)

    def test_case_summary_and_per_case_baseline(self):
        saved,source=self.fixture()
        result=analyze(
            {'suite':'repocontextbench','cases':[saved]},
            [source], FakeRepo())
        self.assertEqual(result['summary']['case_count'],1)
        self.assertEqual(result['summary']['gold_spans_total'],3)
        self.assertEqual(result['summary']['per_case_total_char_budget'],3000)
        self.assertEqual(result['summary']['budgets']['0']['alternate_windows_emitted'],0)


if __name__=='__main__':
    unittest.main()
