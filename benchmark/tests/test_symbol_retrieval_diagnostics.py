"""Offline diagnostics tests; never invoke Ollama or rerun benchmarks."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark import symbol_retrieval_diagnostics as d


def machine(refs, candidates, observed=()):
    evidence=[{'provenance':'investigation','path':p,'line':n} for p,n in refs]
    history=[{'observation':{'path':p,'content':f'{n} | code'},
              'source_refs':[f'{p}:{n}']} for p,n in observed]
    return ({'machine_result_available':True},
            {'evidence':evidence,
             'investigation':{'file_discovery':{'candidates':candidates},
                              'steps':history,'steps_used':len(history)}})


class SymbolRetrievalDiagnosticTests(unittest.TestCase):
    def test_detects_lost_gold_span_without_claiming_causality(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'src').mkdir()
            (root/'src'/'main.f90').write_text('\n'.join('line' for _ in range(50)))
            (root/'src'/'other.f90').write_text('\n'.join('line' for _ in range(50)))
            case={'id':'c1','question':'Where is restore_state?',
                  'gold_spans':[{'id':'E1','path':'src/main.f90',
                                 'start_line':10,'end_line':16}]}
            baseline=machine([('src/main.f90',12)],
                             [{'path':'src/main.f90'}],
                             observed=[('src/main.f90',12)])
            variant=machine([('src/other.f90',20)],
                            [{'path':'src/other.f90',
                              'retrieval_views':['dense','exact-symbol']}],
                            observed=[('src/other.f90',20)])
            matches=[{'path':'src/other.f90','line_hint':20}]
            report=d.analyze_case(case,root,baseline,variant,matches)
            self.assertEqual(report['delta']['lost_gold_spans'],['E1'])
            self.assertEqual(report['delta']['lost_gold_files'],['src/main.f90'])
            self.assertIn('lost_span_not_observed',report['delta']['flags'])
            self.assertIn('gold_file_displaced_from_top8',report['delta']['flags'])
            self.assertNotIn('no_exact_symbol_match',report['delta']['flags'])

    def test_missing_exact_symbols_flagged(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'src').mkdir()
            (root/'src'/'main.f90').write_text('line\n')
            case={'id':'c2','question':'How?','gold_spans':[]}
            base=machine([],[])
            report=d.analyze_case(case,root,base,base,[])
            self.assertIn('no_exact_symbol_match',report['delta']['flags'])


if __name__=='__main__':
    unittest.main()
