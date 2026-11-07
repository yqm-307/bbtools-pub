#!/usr/bin/env python3
"""Local complexity CLI. Source trees, baselines and ignores are read-only."""
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys
import tomllib

from common import AnalysisError, VERSION, require, config_load, json_load, baseline_load, finalize
import semantic
import structural


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version=VERSION)
    commands = p.add_subparsers(dest='command', required=True)
    for name in ('scan', 'prepare', 'score'):
        command = commands.add_parser(name)
        command.add_argument('--root', type=Path, default=Path('.'))
        command.add_argument('--config', type=Path)
        command.add_argument('--output', type=Path, help='Create a new output file; never overwrite')
        if name != 'prepare':
            command.add_argument('--format', choices=('json', 'markdown', 'github'), default='json')
            command.add_argument('--ignore', type=Path)
            command.add_argument('--baseline', type=Path, help='A complete JSON report from the same command')
        if name != 'score':
            command.add_argument('--base', help='Git base reference; resolve before reading sources')
            command.add_argument('--base-mode', choices=('merge-base', 'commit'), default='merge-base')
        if name == 'prepare':
            command.add_argument('--unit', required=True)
            command.add_argument('--scenario', required=True)
            command.add_argument('--file', action='append', default=[])
            command.add_argument('--consumer', action='append', default=[])
            command.add_argument('--contract', action='append', default=[])
        elif name == 'score':
            command.add_argument('--packet', type=Path, required=True)
            command.add_argument('--reviews', type=Path, required=True)
    return p


def markdown(report):
    def cell(value):
        return html.escape(str(value)).replace('|', '&#124;').replace(chr(10), ' ')
    lines = ['# Complexity report', '',
             'Status: ' + report['analysis_status'],
             'Warnings: ' + str(report['summary']['warnings']),
             'Comparison: ' + report['comparison_status'], '',
             '| Rule / root cause | Unit | Result | State | Warning |',
             '|---|---|---|---|---|']
    for f in report['findings']:
        values = (f.get('root_cause', f['rule']), f['unit'], f.get('levels', f.get('after')),
                  f.get('ignore_status', f['status']), f['warning'])
        lines.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    lines.extend(['', 'Coverage: ' + cell(report['coverage']),
                  'Semantic status: ' + cell(report.get('semantic_status', report.get('provenance'))),
                  'Unmatched baseline entries: ' + str(len(report['unmatched_baseline']))])
    return chr(10).join(lines)


def github(report):
    def escape(value):
        return str(value).replace('%', '%25').replace(chr(13), '%0D').replace(chr(10), '%0A').replace(',', '%2C').replace(':', '%3A')
    lines = []
    for f in report['findings']:
        if f['warning']:
            location = ' file=' + escape(f['path']) + ',line=' + str(f['line']) if 'path' in f else ''
            message = f['rule'] + ': ' + f['unit'] + ' ' + str(f.get('levels', f.get('after')))
            lines.append('::warning' + location + '::' + escape(message))
    lines.append('Complexity: ' + report['analysis_status'] + '; warnings=' + str(report['summary']['warnings']))
    if report['coverage']['skipped']:
        lines.append('::error::Incomplete analysis; inspect JSON coverage')
    return chr(10).join(lines)


def run(args):
    root = args.root.resolve()
    require(root.is_dir(), 'Repository root does not exist')
    config = config_load(args.config)
    if args.command == 'prepare':
        base = structural.resolve_base(root, args.base, args.base_mode) if args.base else None
        packet = semantic.prepare(root, args.unit, args.scenario,
                                  {'implementation': args.file, 'consumer': args.consumer, 'contract': args.contract},
                                  config, base)
        return packet, 0
    if args.command == 'scan':
        require(not (args.base and args.baseline), 'Choose --base or --baseline, not both')
        base = structural.resolve_base(root, args.base, args.base_mode) if args.base else None
        report = structural.scan(root, config)
        if base:
            old = structural.scan(root, config, base)
            require(not old['coverage']['skipped'], 'Base scan incomplete: ' + json.dumps(old['coverage']['skipped'], ensure_ascii=False))
        else:
            old = baseline_load(args.baseline, report)
        findings = structural.compare(report, old, config)
    else:
        packet, reviews = json_load(args.packet), json_load(args.reviews)
        old = baseline_load(args.baseline, {'kind': 'semantic'})
        report, findings = semantic.score(root, packet, reviews, config, old)
    code = finalize(report, findings, config, args.ignore)
    return report, code


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        require(args.output is None or not args.output.exists(), 'Output exists; choose a new path')
        report, code = run(args)
        fmt = getattr(args, 'format', 'json')
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) if fmt == 'json' else (markdown(report) if fmt == 'markdown' else github(report))
        if args.output:
            # Exclusive creation prevents overwriting a baseline, source or stale report.
            with args.output.open('x', encoding='utf-8') as output:
                output.write(text + chr(10))
        else:
            print(text)
        return code
    except (AnalysisError, OSError, UnicodeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'analysis_status': 'analysis_error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
