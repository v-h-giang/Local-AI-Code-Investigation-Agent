"""Optional 30-case benchmark. All caches and reports live below benchmark/.

No production imports, patches, or source edits. Standard library only.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / 'datasets' / 'benchmark_30.jsonl'
RESULTS = HERE / 'results'
CACHES = HERE / 'repositories'
REPOS = {
    'repocontextbench': ('microsoft/agent-framework', '47fa59f8e9d7b91e382834b42ecff45e22e2d890', 'agent-framework'),
    'stackrepoqa': ('jdbi/jdbi', '567155b46a00ac131fb51e2ffbce92ebe843a639', 'jdbi'),
}


def read_cases(path=DATA):
    cases = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = set()
    for item in cases:
        if not all(isinstance(item.get(k), str) and item[k] for k in ('id', 'suite', 'repo', 'commit', 'question')):
            raise ValueError('Case missing required string fields')
        if item['suite'] not in REPOS:
            raise ValueError('Unknown benchmark suite')
        repository, commit, _ = REPOS[item['suite']]
        if (item['repo'], item['commit']) != (repository, commit):
            raise ValueError('Dataset repository or commit differs from locked configuration')
        if item['id'] in ids:
            raise ValueError('Duplicate case ID')
        ids.add(item['id'])
    return cases


def check_run_id(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,90}', value) or value in ('.', '..'):
        raise ValueError('Invalid run ID')
    return value


def git(*args, cwd=None, timeout=1800):
    p = subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True,
                       encoding='utf-8', errors='replace', timeout=timeout)
    if p.returncode:
        raise RuntimeError('git failed: ' + p.stderr[-500:])
    return p.stdout.strip()


def ensure_repo(suite, preferred, fetch):
    slug, sha, folder = REPOS[suite]
    path = Path(preferred or (CACHES / folder)).expanduser().resolve()
    if not path.exists():
        if not fetch:
            raise RuntimeError('Source missing: ' + str(path) + '; use --fetch-repos')
        path.parent.mkdir(parents=True, exist_ok=True)
        git('clone', '--filter=blob:none', 'https://github.com/' + slug + '.git', str(path))
    if not (path / '.git').exists():
        raise RuntimeError('Not a Git checkout: ' + str(path))
    head = git('rev-parse', 'HEAD', cwd=path)
    if head != sha:
        if not fetch:
            raise RuntimeError('Wrong commit in ' + str(path) + ': ' + head + ', expected ' + sha)
        if git('status', '--porcelain', cwd=path):
            raise RuntimeError('Dirty checkout; refusing to overwrite: ' + str(path))
        git('fetch', '--depth', '1', 'origin', sha, cwd=path)
        git('checkout', '--detach', sha, cwd=path)
    if git('rev-parse', 'HEAD', cwd=path) != sha:
        raise RuntimeError('Frozen commit validation failed')
    return path


def valid_ref(project, ref):
    if not isinstance(ref, dict):
        return None
    path = str(ref.get('path') or '').replace('\\', '/')
    try:
        line = int(ref.get('line', 0))
    except (ValueError, TypeError):
        return None
    if not path or line < 1 or Path(path).is_absolute() or '..' in Path(path).parts:
        return None
    root = Path(project).resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or not file.is_file():
        return None
    try:
        with file.open(encoding='utf-8', errors='replace') as stream:
            if sum(1 for _ in stream) < line:
                return None
    except OSError:
        return None
    return path, line


def score_evidence(project, case, record):
    raw = record.get('evidence', [])
    raw = raw if isinstance(raw, list) else []
    rows = [x for x in raw if isinstance(x, dict) and x.get('provenance') == 'investigation']
    refs = [found for x in rows if (found := valid_ref(project, x))]
    gold = case.get('gold_spans') or []
    hits = sum(any(path == x['path'] and x['start_line'] <= ln <= x['end_line']
                   for path, ln in refs) for x in gold)
    return {
        'evidence_items': len(rows), 'valid_evidence_items': len(refs),
        'citation_validity': round(len(refs) / len(rows), 4) if rows else None,
        'gold_spans': len(gold), 'gold_span_hits': hits,
        'gold_span_recall_proxy': round(hits / len(gold), 4) if gold else None,
    }


def load_machine(case_dir, stdout):
    match = re.search(r'^Technical JSON:\s*(.+)$', stdout, re.MULTILINE)
    if match:
        path = Path(match.group(1).strip().strip('"'))
        if path.is_file() and path.resolve().is_relative_to(case_dir.resolve()):
            return json.loads(path.read_text(encoding='utf-8'))
    matches = list((case_dir / 'middle-files' / 'investigations').glob('*.json'))
    if len(matches) == 1:
        return json.loads(matches[0].read_text(encoding='utf-8'))
    raise RuntimeError('No unique machine-readable investigation JSON found')



def machine_metrics(case, project, folder, stdout=''):
    """Consume a completed machine record, independent of the CLI's console exit."""
    machine = load_machine(folder, stdout)
    metrics = score_evidence(project, case, machine)
    investigation = machine.get('investigation') or {}
    metrics['answer_status'] = investigation.get('answer_status')
    metrics['answer_text'] = str(investigation.get('answer') or '')[:12000]
    metrics['machine_result_available'] = True
    return str(machine.get('status', 'unknown')), metrics


def recover_existing(case, project, folder, previous):
    """Reuse a saved machine record even when Windows console printing crashed."""
    previous = dict(previous)
    stdout_file = folder / 'stdout.txt'
    stdout = stdout_file.read_text(encoding='utf-8', errors='replace') if stdout_file.is_file() else ''
    try:
        status, metrics = machine_metrics(case, project, folder, stdout)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    previous.update(metrics)
    previous['status'] = status
    previous['recovered_from_machine'] = True
    if previous.get('exit_code') not in (0, None):
        previous['cli_warning'] = 'CLI exited nonzero; machine record was preserved'
    (folder / 'runner_record.json').write_text(
        json.dumps(previous, indent=2, ensure_ascii=False), encoding='utf-8')
    return previous


def run_case(case, project, agent, run_dir, args):
    folder = run_dir / case['id']
    folder.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(agent), '--project', str(project),
           '--model', args.model, '--host', args.host,
           'investigate', case['question'], '--out', str(folder),
           '--max-steps', str(args.max_steps), '--review-rounds',
           str(args.review_rounds if args.mode == 'ai' else 0),
           '--non-diagram', '--non-update-drawio', '--report-format', 'md']
    if args.mode == 'non-ai':
        cmd.append('--non-ai')
    else:
        cmd += ['--max-llm-calls', str(args.max_llm_calls)]
    started = time.perf_counter()
    stdout = stderr = ''
    returncode = None
    status = 'failed'
    metrics = {}
    try:
        # Redirected Python stdout on Japanese Windows may default to CP932.
        # Parent-side encoding='utf-8' alone does not set the CHILD encoding.
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=args.timeout,
                                env=env)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        try:
            status, metrics = machine_metrics(case, project, folder, stdout)
            if returncode:
                metrics['cli_warning'] = ('CLI exited with ' + str(returncode) +
                                         ' after writing a machine record')
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            metrics = {'machine_result_available': False,
                       'error': type(exc).__name__ + ': ' + str(exc)[:500]}
            if returncode:
                metrics['error'] = ('agent exited with ' + str(returncode) +
                                    '; ' + metrics['error'])
            if stderr:
                metrics['stderr_tail'] = stderr[-1500:]
    except subprocess.TimeoutExpired as exc:
        def as_text(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')
        stdout, stderr = as_text(exc.stdout), as_text(exc.stderr)
        status, metrics = 'timeout', {'machine_result_available': False,
                                      'error': 'CLI timeout after ' + str(args.timeout) + 's'}
        if stderr:
            metrics['stderr_tail'] = stderr[-1500:]
    except Exception as exc:
        metrics = {'machine_result_available': False,
                   'error': type(exc).__name__ + ': ' + str(exc)[:500]}
    record = {'id': case['id'], 'suite': case['suite'], 'repo': case['repo'],
              'mode': args.mode, 'status': status, 'exit_code': returncode,
              'elapsed_seconds': round(time.perf_counter() - started, 3), **metrics}
    (folder / 'runner_record.json').write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    (folder / 'stdout.txt').write_text(stdout[-300000:], encoding='utf-8')
    (folder / 'stderr.txt').write_text(stderr[-300000:], encoding='utf-8')
    return record


def save_report(run_dir, records, args, selected_count):
    records = sorted(records, key=lambda x: x['id'])
    times = [x['elapsed_seconds'] for x in records]
    validity = [x['citation_validity'] for x in records if x.get('citation_validity') is not None]
    gold = sum(x.get('gold_spans', 0) for x in records)
    hits = sum(x.get('gold_span_hits', 0) for x in records)
    failed = sum(not x.get('machine_result_available', False) for x in records)
    missing = max(0, selected_count - len(records))
    summary = {'suite': args.suite, 'mode': args.mode, 'selected_cases': selected_count,
               'recorded_cases': len(records),
               'successful_cli_calls': sum(x.get('exit_code') == 0 for x in records),
               'cli_nonzero_exits': sum(x.get('exit_code') not in (0, None) for x in records),
               'recovered_machine_records': sum(x.get('recovered_from_machine', False) for x in records),
               'machine_results_available': sum(x.get('machine_result_available', False) for x in records),
               'failed_or_timed_out': failed + missing,
               'elapsed_seconds_total': round(sum(times), 3),
               'median_seconds': round(statistics.median(times), 3) if times else None,
               'mean_citation_validity': round(statistics.mean(validity), 4) if validity else None,
               'gold_span_recall_proxy': round(hits / gold, 4) if gold else None,
               'note': 'Evidence overlap is not answer correctness or an official RepoContextBench score.'}
    (run_dir / 'results.json').write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
    (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    csvfile = run_dir / 'review_template.csv'
    if not csvfile.is_file():
        with csvfile.open('w', newline='', encoding='utf-8-sig') as file:
            w = csv.writer(file)
            w.writerow(['id', 'suite', 'correctness_0_to_4', 'grounded_yes_no', 'notes'])
            for row in records:
                w.writerow([row['id'], row['suite'], '', '', ''])
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description='Standalone optional benchmark runner')
    p.add_argument('--list', action='store_true')
    p.add_argument('--suite', choices=['all', 'repocontextbench', 'stackrepoqa'], default='all')
    p.add_argument('--mode', choices=['ai', 'non-ai'], default='ai')
    p.add_argument('--limit', type=int)
    p.add_argument('--fetch-repos', action='store_true')
    p.add_argument('--repocontextbench-path', type=Path)
    p.add_argument('--stackrepoqa-path', type=Path)
    p.add_argument('--agent', type=Path, default=ROOT / 'agent.py')
    p.add_argument('--model', default='qwen3:8b')
    p.add_argument('--host', default='http://127.0.0.1:11434')
    p.add_argument('--max-steps', type=int, default=4)
    p.add_argument('--review-rounds', type=int, default=1)
    p.add_argument('--max-llm-calls', type=int, default=80)
    p.add_argument('--timeout', type=int, default=1800)
    p.add_argument('--run-id', default='baseline')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--retry-failed', action='store_true',
                   help='With --resume, rerun only failed cases lacking recoverable machine JSON')
    args = p.parse_args(argv)
    cases = [c for c in read_cases() if args.suite == 'all' or c['suite'] == args.suite]
    if args.limit is not None:
        if args.limit < 1:
            p.error('--limit must be positive')
        cases = cases[:args.limit]
    if args.retry_failed and not args.resume:
        p.error('--retry-failed requires --resume')
    if args.list:
        for c in cases:
            print(c['id'], '[' + c['suite'] + ']', c['question'].splitlines()[0][:160])
        print('Total:', len(cases))
        return 0
    try:
        check_run_id(args.run_id)
    except ValueError as exc:
        p.error(str(exc))
    agent = args.agent.expanduser().resolve()
    if not agent.is_file():
        p.error('Agent CLI not found: ' + str(agent))
    run_dir = RESULTS / args.run_id
    if run_dir.exists() and not args.resume:
        p.error('Run exists; change --run-id or provide --resume')
    projects = {}
    for suite in dict.fromkeys(c['suite'] for c in cases):
        projects[suite] = ensure_repo(suite, getattr(args, suite + '_path'), args.fetch_repos)
    run_dir.mkdir(parents=True, exist_ok=True)
    configuration = {'suite': args.suite, 'mode': args.mode, 'model': args.model, 'host': args.host,
                     'repository_commits': {suite: REPOS[suite][1] for suite in projects}}
    cfgfile = run_dir / 'run_config.json'
    if cfgfile.is_file():
        if json.loads(cfgfile.read_text(encoding='utf-8')) != configuration:
            p.error('Cannot resume a run with changed model, suite, mode, or commit')
    else:
        cfgfile.write_text(json.dumps(configuration, indent=2), encoding='utf-8')
    records = {}
    for case in cases:
        old = run_dir / case['id'] / 'runner_record.json'
        if args.resume and old.is_file():
            previous = json.loads(old.read_text(encoding='utf-8'))
            if not previous.get('machine_result_available'):
                recovered = recover_existing(case, projects[case['suite']], old.parent, previous)
                if recovered:
                    records[case['id']] = recovered
                    print(case['id'], 'recovered machine JSON; no AI rerun', flush=True)
                    continue
            if previous.get('machine_result_available') or not args.retry_failed:
                records[case['id']] = previous
                if not previous.get('machine_result_available'):
                    print(case['id'], 'previous failure; inspect stderr.txt or use --retry-failed', flush=True)
                continue
        result = run_case(case, projects[case['suite']], agent, run_dir, args)
        records[case['id']] = result
        save_report(run_dir, list(records.values()), args, len(cases))
        detail = result.get('error') or result.get('cli_warning') or ''
        print(case['id'], result['status'], result['elapsed_seconds'], 'seconds',
              detail[:200], flush=True)
    summary = save_report(run_dir, list(records.values()), args, len(cases))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['failed_or_timed_out'] == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
