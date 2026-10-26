"""Local Code Investigation Agent - CLI for Windows/VS Code."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from codebase import Repo
from agent_core import Investigator, Ollama, OllamaError
from exporter import export_design, export_static
from overview import export_overview
from system_memory import print_ram_status


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only local AI investigation of Java / SQL / Adobe AIR source')
    p.add_argument('--project', required=True, help='Local source project directory')
    p.add_argument('--model', default='qwen3:8b', help='Ollama local model tag (default qwen3:8b)')
    p.add_argument('--host', default='http://127.0.0.1:11434', help='Loopback Ollama endpoint')
    p.add_argument('--num-ctx', type=int, default=2048, help='Ollama context tokens (default 2048, suitable for limited RAM)')
    p.add_argument('--timeout', type=int, default=240, help='HTTP response timeout in seconds (default 240)')
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor', help='Verify Ollama and report source summary')
    d.add_argument('--probe', action='store_true', help='Actually load model and generate a tiny reply')
    sub.add_parser('index', help='Rebuild local SQLite FTS search index')
    s = sub.add_parser('architecture', help='Fast static architecture, libraries and file links (NO Ollama)')
    s.add_argument('--out', default='output/architecture', help='Output folder')
    s.add_argument('--ai-summary', action='store_true', help='Summarize each module using local Ollama (optional)')
    s.add_argument('--auto-investigate-top',type=int,default=0,metavar='N',help='Run the N highest-ranked suggested investigations with Qwen (1-20); default: disabled')
    s = sub.add_parser('intelligence', help='Incrementally build symbol/call/search/SQL intelligence index')
    s.add_argument('--out', default='output/architecture')
    s = sub.add_parser('investigate', help='Investigate with local Qwen by default; --non-ai for retrieval only')
    s.add_argument('question'); s.add_argument('--budget',type=int,default=1200)
    s.add_argument('--max-steps',type=int,default=4,help='Maximum read-only tool investigation steps (1-6)')
    s.add_argument('--non-ai',action='store_true',help='Disable Qwen and use local lexical evidence retrieval only')
    s = sub.add_parser('symbol',help='Symbol declarations and references from local intelligence index')
    s.add_argument('name')
    s = sub.add_parser('trace',help='Candidate caller-callee and static dependency graph')
    s.add_argument('name'); s.add_argument('--depth',type=int,default=3)
    s.add_argument('--direction',choices=['out','in'],default='out')
    s = sub.add_parser('impact',help='Reverse dependency and caller impact candidates')
    s.add_argument('name');s.add_argument('--depth',type=int,default=4)
    s = sub.add_parser('clusters',help='Connected code graph components')
    s = sub.add_parser('flows',help='Entrypoint, dependency, and SQL evidence inventory')
    s = sub.add_parser('diff-impact',help='Trace file impact from local Git diff')
    s.add_argument('--base',default='HEAD~1');s.add_argument('--head',default='HEAD')
    s = sub.add_parser('vectorize',help='Optional bounded local Ollama symbol embedding index')
    s.add_argument('--embedding-model',default='nomic-embed-text');s.add_argument('--max-symbols',type=int,default=200)
    s = sub.add_parser('semantic',help='Vector similarity across locally embedded symbol signatures')
    s.add_argument('query');s.add_argument('--embedding-model',default='nomic-embed-text')
    s = sub.add_parser('history',help='Read local Git history for code investigation')
    s.add_argument('--file',default=None);s.add_argument('--limit',type=int,default=20)
    for cmd_name in ('investigate','symbol','trace','impact','clusters','flows','history','diff-impact','vectorize','semantic'):
        sub.choices[cmd_name].add_argument('--out',default='output/architecture',help='Index/output directory')
    s = sub.add_parser('search', help='Literal source search without AI')
    s.add_argument('query'); s.add_argument('--pattern', default='*'); s.add_argument('--limit', type=int,default=30)
    s = sub.add_parser('refs', help='Find symbol references without AI'); s.add_argument('symbol')
    s = sub.add_parser('read', help='Read a file with line numbers'); s.add_argument('path'); s.add_argument('--start',type=int,default=1); s.add_argument('--end',type=int,default=120)
    s = sub.add_parser('ask', help='Ask one AI question'); s.add_argument('question')
    sub.add_parser('chat',help='Interactive session; /exit to quit')
    s = sub.add_parser('report',help='Generate offline static inventory and editable .drawio diagram')
    s.add_argument('--topic',default=''); s.add_argument('--out',default='output')
    s = sub.add_parser('overview',help='Automatically survey the full repository without a topic (optional AI)')
    s.add_argument('--out',default='output/overview'); s.add_argument('--ai',action='store_true',help='Also write AI architecture design using local Ollama')
    s.add_argument('--max-batches',type=int,default=None,help='Optional debug-only cap; default: no limit'); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    s = sub.add_parser('design',help='With --topic: feature design; without --topic: automated repo overview + AI')
    s.add_argument('--topic',default=''); s.add_argument('--out',default=None)
    s.add_argument('--max-batches',type=int,default=None,help='Optional debug-only cap; default: no limit'); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    a = p.parse_args(argv)
    print_ram_status()
    try:
        repo = Repo(a.project)
        if a.command=='index': print(json.dumps(repo.index(),ensure_ascii=False,indent=2));return 0
        if a.command=='architecture':
            from architecture import export_architecture
            from module_summary import summarize_modules
            result = export_architecture(repo,a.out)
            llm = Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx) if a.ai_summary else None
            result.update(summarize_modules(repo,a.out,llm=llm))
            from stack_architecture import export_stack_architecture
            result.update(export_stack_architecture(repo,a.out))
            from suggested_investigations import suggest_investigations, auto_investigate
            if a.auto_investigate_top < 0 or a.auto_investigate_top > 20:
                raise ValueError('--auto-investigate-top must be between 1 and 20, or omitted')
            suggestions = suggest_investigations(repo,a.out,top=20)
            candidates = suggestions.pop('candidates')
            result.update(suggestions)
            if a.auto_investigate_top:
                ai = llm or Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx)
                result['auto_investigation'] = auto_investigate(repo,a.out,candidates,
                    a.auto_investigate_top,ai)
                if result['auto_investigation']['successful'] != result['auto_investigation']['executed']:
                    print(json.dumps(result,ensure_ascii=False,indent=2));return 2
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.command in ('intelligence','investigate','symbol','trace','impact','clusters','flows','history','diff-impact','vectorize','semantic'):
            from code_intelligence import (build_intelligence, investigate, symbol_query, trace,
                impact, clusters, business_flows, git_history, diff_impact, vectorize, vector_search)
            repo.intelligence_db=(Path(a.out).expanduser().resolve()/'middle-files'/'code_intelligence.sqlite')
            if a.command=='intelligence': result=build_intelligence(repo,a.out)
            elif a.command=='history':result=git_history(repo,a.file,a.limit)
            elif a.command=='diff-impact':result=diff_impact(repo,a.base,a.head)
            elif a.command=='vectorize':result=vectorize(repo,a.host,a.embedding_model,a.max_symbols)
            elif a.command=='semantic':result=vector_search(repo,a.query,a.host,a.embedding_model)
            elif a.command=='symbol':result=symbol_query(repo,a.name)
            elif a.command=='trace':result=trace(repo,a.name,a.depth,a.direction)
            elif a.command=='impact':result=impact(repo,a.name,a.depth)
            elif a.command=='clusters':result=clusters(repo)
            elif a.command=='flows':result=business_flows(repo)
            else:
                llm=None if a.non_ai else Ollama(a.host,a.model,timeout=a.timeout,num_ctx=a.num_ctx)
                result=investigate(repo,a.question,llm,budget=a.budget,max_steps=a.max_steps)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.command=='search': print(repo.search_code(a.query, a.pattern, a.limit));return 0
        if a.command=='refs': print(repo.find_symbol(a.symbol));return 0
        if a.command=='read': print(repo.read_file(a.path,a.start,a.end));return 0
        if a.command=='report': print(json.dumps(export_static(repo,a.topic,a.out),ensure_ascii=False,indent=2));return 0
        if a.command=='overview' and not a.ai:
            print(json.dumps(export_overview(repo,a.out),ensure_ascii=False,indent=2));return 0
        if a.command in ('ask', 'chat', 'design', 'overview'):
            print('[Index] Checking local source index...', flush=True)
            info = repo.ensure_index()
            print(f'[Index] {info["status"]}: {info["files"]} files; DB: {info["database"]}', flush=True)
        llm = Ollama(a.host, a.model, timeout=a.timeout, num_ctx=a.num_ctx)
        if a.command=='doctor':
            print(f'Project: {repo.root}\nSample files:\n{repo.list_files(limit=15)}\n{llm.health()}')
            if a.probe:
                print(llm.probe())
            return 0
        if a.command=='overview':
            print('[Overview] Surveying repository and generating outputs...', flush=True)
            result=export_overview(repo,a.out,llm=llm,max_batches=a.max_batches,files_per_batch=a.files_per_batch,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status')=='incomplete' else 0
        if a.command=='design':
            print('[Design] Analyzing source and writing documents...', flush=True)
            dest=a.out or ('output' if a.topic.strip() else 'output/overview')
            result = export_design(repo,llm,a.topic,dest) if a.topic.strip() else export_overview(repo,dest,llm=llm,max_batches=a.max_batches,files_per_batch=a.files_per_batch,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status')=='incomplete' else 0
        inv = Investigator(repo,llm)
        if a.command=='ask': print('\n'+inv.ask(a.question));return 0
        if a.command=='chat':
            print('Local AI Code Agent - /overview (quét offline), /design-all (AI overview), /exit, /clear.')
            while True:
                try: question=input('\nBạn> ').strip()
                except (EOFError,KeyboardInterrupt):break
                if question.lower() in ('/exit','exit','quit'):break
                if question.lower()=='/clear': inv=Investigator(repo,llm);print('Đã xóa lịch sử.');continue
                if question.lower() in ('/overview','/design-all'):
                    info=export_overview(repo,'output/overview',llm=llm if question.lower()=='/design-all' else None)
                    print(json.dumps(info,ensure_ascii=False,indent=2));continue
                if question: print('\nAgent> '+inv.ask(question))
            return 0
    except (OllamaError,ValueError,OSError,KeyboardInterrupt) as e:
        print('ERROR:',e,file=sys.stderr);return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
