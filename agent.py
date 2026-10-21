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
    s.add_argument('--max-batches',type=int,default=None); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    s = sub.add_parser('design',help='With --topic: feature design; without --topic: automated repo overview + AI')
    s.add_argument('--topic',default=''); s.add_argument('--out',default=None)
    s.add_argument('--max-batches',type=int,default=None); s.add_argument('--files-per-batch',type=int,choices=[1,2],default=1); s.add_argument('--no-resume',action='store_true')
    a = p.parse_args(argv)
    print_ram_status()
    try:
        repo = Repo(a.project)
        if a.command=='index': print(json.dumps(repo.index(),ensure_ascii=False,indent=2));return 0
        if a.command=='architecture':
            from architecture import export_architecture
            print(json.dumps(export_architecture(repo,a.out),ensure_ascii=False,indent=2));return 0
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
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status') == 'incomplete' else 0
        if a.command=='design':
            print('[Design] Analyzing source and writing documents...', flush=True)
            dest=a.out or ('output' if a.topic.strip() else 'output/overview')
            result = export_design(repo,llm,a.topic,dest) if a.topic.strip() else export_overview(repo,dest,llm=llm,max_batches=a.max_batches,files_per_batch=a.files_per_batch,resume=not a.no_resume)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('status') == 'incomplete' else 0
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
