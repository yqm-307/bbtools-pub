#!/usr/bin/env python3
"""只读 C++ 全量候选扫描；告警不是缺陷或语义验证结论。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'core'))
from configuration import CONFIG, load_config
from cpp import EXTENSIONS
from scan import Scan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='源码目录；输出与排除路径相对于它')
    parser.add_argument('--config', type=Path, help='统一 TOML 配置；缺省向上查找 .config/lint.toml')
    parser.add_argument('--format', choices=('text', 'json', 'diagnostic'),
                        help='设计检查默认 diagnostic（带源码），普通扫描默认 text；json 供程序读取')
    parser.add_argument('--design', action='store_true', help='运行只报告的设计检查')
    parser.add_argument('--lang', choices=('en', 'zh'), help='设计检查报告的语言；默认 en，中文用 zh')
    parser.add_argument('--check', action='append', default=[], help='只列指定设计检查，可重复')
    parser.add_argument('--baseline', help='设计历史检查的 Git 基准')
    args = parser.parse_args()
    if args.format is None:
        args.format = 'diagnostic' if args.design else 'text'
    if args.format == 'diagnostic' and not args.design:
        parser.error('--format diagnostic requires --design')
    if not args.design and (args.check or args.baseline):
        parser.error('--check and --baseline require --design')
    if not args.design and args.lang:
        parser.error('--lang requires --design')
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError('root must be a directory')
        path = args.config or next((p / CONFIG for p in (root, *root.parents)
                                    if (p / CONFIG).is_file()), None)
        if args.design:
            from design import run
            return run(root, path, args)
        cfg = load_config(path)
        scan = Scan(root, cfg, cfg['scan']['rules'])
        for file in sorted(root.rglob('*')):
            if file.suffix in EXTENSIONS and (file.is_file() or file.is_symlink()):
                scan.file(file)
        if not scan.files:
            scan.emit('.', 1, 'T000', 'incomplete: no source files scanned')
        report = scan.report()
        if args.format == 'json':
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for row in report['findings']:
                print(f'{row["file"]}:{row["line"]} {row["rule"]} warn {row["message"]}')
        print(f'lexical scan: files={scan.files}, partial={len(scan.partial)}, '
              f'warnings={len(scan.rows)}, excluded={len(scan.excluded)}; no semantic pass claimed', file=sys.stderr)
        return 2 if scan.partial else 0
    except (OSError, ValueError) as error:
        print(f'.:1 T000 warn incomplete: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
