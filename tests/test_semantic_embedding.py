"""Offline unit tests for semantic retrieval. No Ollama or network required."""
from __future__ import annotations
from array import array
from pathlib import Path
import sqlite3
import tempfile
import unittest

from semantic_retrieval import (
    OllamaEmbedder, _chunk_lines, _rrf, dense_search, hybrid_search, index_project,
    require_local_host,
)


class FakeRepo:
    def __init__(self,root):
        self.root=Path(root).resolve()
    def _safe(self,path):
        p=(self.root/path).resolve()
        if not p.is_relative_to(self.root) or not p.is_file():
            raise ValueError('Bad source path')
        return p
    def _read(self,path):
        return path.read_text(encoding='utf-8')


class FakeEmbedder:
    model='qwen3-embedding:0.6b'
    dimensions=4
    calls=[]
    def embed(self, texts, *, query=False, keep_alive='5m'):
        self.calls.append((query, len(texts)))
        result=[]
        for text in texts:
            lower=text.lower()
            if any(w in lower for w in ('checkpoint','restore','resume','restart')):
                result.append(array('f',[1,0,0,0]))
            elif 'save_order' in lower or 'order' in lower:
                result.append(array('f',[0,1,0,0]))
            else:
                result.append(array('f',[0,0,1,0]))
        return result


class SemanticEmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.repo=FakeRepo(self.folder/'project')
        self.repo.root.mkdir()
        (self.repo.root/'checkpoint_impl.f90').write_text(
            'module state_store\ncontains\nsubroutine restore_checkpoint()\n'
            'print *, "restored"\nend subroutine\nend module\n',encoding='utf-8')
        (self.repo.root/'orders.f90').write_text(
            'subroutine save_order\nprint *, "saved"\nend subroutine\n',encoding='utf-8')
        self.intelligence=self.folder/'intelligence.sqlite'
        from contextlib import closing
        with closing(sqlite3.connect(self.intelligence)) as conn:
            with conn:
                conn.execute('CREATE TABLE files (path TEXT PRIMARY KEY)')
                conn.executemany('INSERT INTO files VALUES (?)',
                                 [('checkpoint_impl.f90',),('orders.f90',)])
        self.db=self.folder/'semantic.sqlite'
        self.embedder=FakeEmbedder()

    def test_chunk_lines_preserve_source_ranges(self):
        chunks=list(_chunk_lines([str(n) for n in range(100)],size=48,overlap=12))
        self.assertEqual([(a,b) for a,b,_ in chunks],[(1,48),(37,84),(73,100)])
        self.assertEqual(chunks[-1][2].splitlines()[-1],'99')

    def test_incremental_index_reuses_files_and_caches_vectors(self):
        initial=index_project(self.repo,self.intelligence,self.db,self.embedder)
        self.assertEqual(initial['files_changed'],2)
        self.assertEqual(initial['chunks_total'],2)
        second=index_project(self.repo,self.intelligence,self.db,self.embedder)
        self.assertEqual(second['files_changed'],0)
        self.assertEqual(second['files_reused'],2)
        (self.repo.root/'orders.f90').write_text('subroutine save_order\nstop\nend\n',encoding='utf-8')
        third=index_project(self.repo,self.intelligence,self.db,self.embedder)
        self.assertEqual(third['files_changed'],1)
        self.assertEqual(third['files_reused'],1)

    def test_dense_finds_semantically_related_source_with_real_span(self):
        index_project(self.repo,self.intelligence,self.db,self.embedder)
        found=dense_search(self.repo,'How do I resume execution?',self.db,self.embedder)
        self.assertEqual(found[0]['path'],'checkpoint_impl.f90')
        self.assertEqual(found[0]['start_line'],1)
        self.assertEqual(found[0]['end_line'],6)
        self.assertFalse(found[0]['citation'])

    def test_hybrid_can_admit_dense_only_file(self):
        index_project(self.repo,self.intelligence,self.db,self.embedder)
        sparse=[{'path':'orders.f90','file_role':'implementation','path_score':40}]
        found=hybrid_search(self.repo,'resume workflow',self.db,self.embedder,limit=2,
                            lexical_search=lambda *args,**kw:sparse,
                            source_search=lambda *args,**kw:[])
        self.assertEqual(len(found),2)
        self.assertIn('checkpoint_impl.f90',{x['path'] for x in found})
        self.assertTrue(all(not x['citation'] for x in found))

    def test_bad_host_and_wrong_project_rejected(self):
        for bad in ['https://localhost:11434','http://198.51.100.15:11434',
                    'http://localhost:11434/evil']:
            with self.assertRaises(ValueError):require_local_host(bad)
        self.assertEqual(require_local_host('http://127.0.0.1:11434'),
                         'http://127.0.0.1:11434')
        index_project(self.repo,self.intelligence,self.db,self.embedder)
        different=FakeRepo(self.folder/'other')
        different.root.mkdir()
        with self.assertRaises(ValueError):
            dense_search(different,'resume',self.db,self.embedder)

    def test_no_gold_leaks_into_retriever(self):
        rows=_rrf([('dense',1.0,[{'path':'a.f90','line_hint':3,'start_line':1,'end_line':9}]),
                   ('fts',1.0,[{'path':'b.f90','line':5},{'path':'a.f90','line':2}])],limit=2)
        self.assertEqual(rows[0]['path'],'a.f90')
        self.assertIn('line_hint',rows[0])
        self.assertNotIn('is_gold',rows[0])
        self.assertFalse(rows[0]['citation'])


    def test_hybrid_provides_canonical_source_windows_for_span_scoring(self):
        index_project(self.repo,self.intelligence,self.db,self.embedder)
        found=hybrid_search(self.repo,'resume workflow',self.db,self.embedder,limit=8,
                            lexical_search=lambda *args,**kw:[],
                            source_search=lambda *args,**kw:[])
        self.assertTrue(found)
        with_ranges=[x for x in found if x.get('line_hint_source')=='dense']
        self.assertTrue(with_ranges)
        for row in with_ranges:
            self.assertEqual(row['start_line'],row['line_start'])
            self.assertEqual(row['end_line'],row['line_end'])
            self.assertLessEqual(row['start_line'],row['end_line'])
            self.assertFalse(row['citation'])

    def test_http_400_batch_fallback_and_bounded_chunk_retry(self):
        from semantic_retrieval import _embed_index_rows
        class TooLong:
            def embed(self,texts,*,query=False,keep_alive='5m'):
                if len(texts)>1 or len(texts[0])>1700:
                    raise RuntimeError('Ollama /api/embed HTTP 400: requested context too large')
                return [array('f',[1.0,0.0,0.0,0.0]) for _ in texts]
        longbody=''.join(f"print({n})\n" for n in range(400))
        bad=('bad.f90',1,400,'File: bad.f90\nLines: 1-400\n'+longbody,'first')
        good=('good.f90',1,3,'File: good.f90\nLines: 1-3\na\nb\nc','first')
        stats={'embed_batch_splits':0,'embed_chunk_splits':0,'embed_chunks_shortened':0}
        got=_embed_index_rows(TooLong(),[good,bad],stats)
        self.assertGreater(len(got),2)
        self.assertGreater(stats['embed_batch_splits'],0)
        self.assertGreater(stats['embed_chunk_splits'],0)
        self.assertEqual(stats['embed_chunks_shortened'],0)
        self.assertEqual(got[0][2],3)
        spans=[(item[1], covered_end) for item,vec,covered_end in got
               if item[0]=='bad.f90']
        self.assertEqual(spans[0][0],1)
        self.assertEqual(spans[-1][1],400)
        self.assertTrue(all(spans[i][1]+1==spans[i+1][0]
                            for i in range(len(spans)-1)))

    def test_chunk_shortening_preserves_indexed_source_start(self):
        from semantic_retrieval import _shorten_failed_chunk
        body=''.join('call operation()\n' for _ in range(100))
        chunk=('source.f90',29,128,'File: source.f90\nLines: 29-128\n'+body,'call')
        shortened,covered_end=_shorten_failed_chunk(chunk,900)
        self.assertTrue(shortened.startswith('File: source.f90\nLines: 29-'))
        self.assertTrue(shortened.endswith('\n') or 'call operation' in shortened)
        self.assertGreaterEqual(covered_end,29)
        self.assertLess(covered_end,128)



class SemanticAgentWrapperTests(unittest.TestCase):
    def test_wrapper_uses_indexed_span_to_read_source_and_keeps_baseline(self):
        import sys
        import types
        from unittest.mock import patch
        import semantic_agent
        import semantic_retrieval
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        db=Path(folder.name)/'embeddings.sqlite'
        db.write_bytes(b'fake-test-db')
        fake_agent=types.ModuleType('agent')
        fake_ci=types.ModuleType('code_intelligence')
        fake_loop=types.ModuleType('investigation_loop')
        original_calls=[]
        def original(repo,query,limit=6,*,strategy='v59'):
            original_calls.append(strategy)
            return [{'path':'fallback.f90','file_role':'other'}]
        fake_ci.search_file_candidates=original
        fake_loop._validate_action=lambda action:action
        outcomes={}
        def agent_main(argv):
            outcomes['args']=argv
            outcomes['hybrid']=fake_ci.search_file_candidates(object(),'how does this resume?',limit=8)
            outcomes['baseline']=fake_ci.search_file_candidates(object(),'resume',strategy='baseline')
            outcomes['validated']=fake_loop._validate_action({
                'tool':'search_file','path':'source.f90','query':'resume'})
            return 0
        fake_agent.main=agent_main
        def stub_hybrid(*args,**kwargs):
            return [{'path':'source.f90','file_role':'implementation',
                     'line_hint':18,'line_start':12,'line_end':32,
                     'citation':False}]
        with patch.dict(sys.modules,{
                'agent':fake_agent,
                'code_intelligence':fake_ci,
                'investigation_loop':fake_loop}), \
             patch.object(semantic_retrieval,'hybrid_search',stub_hybrid):
            code=semantic_agent.main([
                '--semantic-db',str(db),'--semantic-mode','hybrid',
                '--project','D:/repo','investigate','resume'])
        self.assertEqual(code,0)
        self.assertEqual(outcomes['hybrid'][0]['path'],'source.f90')
        self.assertEqual(outcomes['baseline'][0]['path'],'fallback.f90')
        self.assertEqual(outcomes['validated']['tool'],'read_source')
        self.assertEqual(outcomes['validated']['path'],'source.f90')
        self.assertEqual(outcomes['validated']['start_line'],4)
        self.assertEqual(outcomes['validated']['end_line'],40)
        self.assertNotIn('--semantic-db',outcomes['args'])


if __name__=='__main__':
    unittest.main()
