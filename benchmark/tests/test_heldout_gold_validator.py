"""Synthetic tests for P1.12 pinned-source gold-coordinate validation."""
import unittest
from benchmark import heldout_gold_validator as gv

SHA='a'*40
REPO='pallets/click'


class DemoRepo:
    def read_file(self,path,lo,hi):
        return '\n'.join(f'{n:5d} | actual source line' for n in range(lo,min(hi,300)+1))


class GoldValidatorTests(unittest.TestCase):
    def fixture(self):
        row={'id':'external_001','suite':'click_external','repo':REPO,
             'commit':SHA,'question':'Where does Click handle retries?'}
        gold={**row,'gold_spans':[{'id':'E1','path':'src/a.py',
                                 'start_line':12,'end_line':17}]}
        return [row],[gold]

    def validate(self,questions,labels,known=()):
        return gv.validate_labels(DemoRepo(),questions,labels,list(known),
                                  repository=REPO,commit=SHA)

    def test_click_bundle_has_distinct_question_only_and_label_files(self):
        from pathlib import Path
        from benchmark.heldout_window_builder import read_questions
        root = Path(__file__).resolve().parents[1] / 'datasets'
        questions = read_questions(root / 'p112_click_questions.jsonl',
                                   repository='pallets/click',
                                   commit='ac0e297ec2d7d78455a7d18ce306996e668c4a85')
        from benchmark.heldout_evidence_eval import _read_jsonl
        labels = _read_jsonl(root / 'p112_click_labels.jsonl')
        self.assertEqual(len(questions), 13)
        self.assertEqual(len(labels), 13)
        self.assertEqual(sum(len(x['gold_spans']) for x in labels), 24)
        self.assertEqual({x['id'] for x in questions}, {x['id'] for x in labels})
        self.assertTrue(all('gold_spans' not in q for q in questions))

    def test_validates_coordinates_and_links(self):
        qs,ls=self.fixture();r=self.validate(qs,ls)
        self.assertEqual(r['gold_span_count'],1)
        self.assertIn('#L12-L17',r['review_links'][0]['source'])
        self.assertEqual(r['review_status'],'coordinates_verified_not_semantics_reviewed')

    def test_rejects_nonexistent_line(self):
        qs,ls=self.fixture();ls[0]['gold_spans'][0]['start_line']=301
        ls[0]['gold_spans'][0]['end_line']=303
        with self.assertRaises(ValueError):self.validate(qs,ls)

    def test_rejects_labels_mismatch(self):
        qs,ls=self.fixture();ls[0]['question']='Changed question'
        with self.assertRaises(ValueError):self.validate(qs,ls)

    def test_rejects_unlabeled(self):
        qs,ls=self.fixture();ls[0]['gold_spans']=[]
        with self.assertRaises(ValueError):self.validate(qs,ls)

    def test_rejects_history_overlap(self):
        qs,ls=self.fixture()
        with self.assertRaises(ValueError):self.validate(qs,ls,[qs[0]])

    def test_rejects_duplicate_ids(self):
        qs,ls=self.fixture();ls[0]['gold_spans'].append(dict(ls[0]['gold_spans'][0]))
        with self.assertRaises(ValueError):self.validate(qs,ls)

    def test_rejects_outside_repository_path(self):
        qs,ls=self.fixture();ls[0]['gold_spans'][0]['path']='../danger.py'
        with self.assertRaises(ValueError):self.validate(qs,ls)

    def test_rejects_unexpected_fields(self):
        qs,ls=self.fixture();ls[0]['gold_spans'][0]['ranking_score']=1
        with self.assertRaises(ValueError):self.validate(qs,ls)


if __name__=='__main__':unittest.main()
