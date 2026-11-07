"""Behavior tests use temporary source trees and explicitly synthetic reviews."""
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import common
import complexity
import semantic
import structural


class ComplexityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'bbt').mkdir()
        self.source = self.root / 'bbt/sample.cc'
        self.source.write_text('int f(int x) { if (x) { if (x > 2) return 1; } return 0; }\n')
        (self.root / 'bbt/caller.cc').write_text('int g() { return f(3); }\n')
        (self.root / 'contract.md').write_text('Provide f without changing ownership.\n')
        self.config = common.config_load()
        self.config['structural']['thresholds']['cognitive_complexity'] = 2
        self.config['structural']['thresholds']['cyclomatic_complexity'] = 2

    def report(self, old=None):
        report = structural.scan(self.root, self.config)
        findings = structural.compare(report, old, self.config)
        common.finalize(report, findings, self.config, None)
        return report

    def packet(self):
        return semantic.prepare(self.root, 'f', 'Call f with one input',
                                {'implementation': ['bbt/sample.cc'], 'consumer': ['bbt/caller.cc'],
                                 'contract': ['contract.md']}, self.config)

    def reviews(self, packet, level=2):
        entry = {'root_cause': 'manual-assembly', 'levels': dict.fromkeys(common.AXES, 0),
                 'burden': 'Synthetic fixture: caller maintains an unnecessary step.',
                 'necessity': 'Synthetic fixture: no safety requirement depends on the step.',
                 'counterevidence': 'Synthetic fixture: an external consumer might rely on it.',
                 'simpler_direction': 'Synthetic fixture: move the step behind the same contract.',
                 'evidence': [{'path': 'bbt/sample.cc', 'version': 'after', 'start_line': 1,
                               'end_line': 1, 'quote': 'int f(int x)'}]}
        entry['levels']['U'] = level
        return {'schema_version': 1, 'packet_digest': packet['packet_digest'],
                'evaluator': {'name': 'synthetic-test-fixture', 'version': '1'},
                'rounds': [{'review_id': str(i), 'context_sufficient': True,
                            'assessed_axes': list(common.AXES), 'findings': [copy.deepcopy(entry)]} for i in range(2)]}

    def semantic_report(self, packet, reviews, old=None):
        report, findings = semantic.score(self.root, packet, reviews, self.config, old)
        code = common.finalize(report, findings, self.config, None)
        return report, code

    def ignore_file(self, finding, **changes):
        entry = {k: finding[k] for k in ('finding_id', 'rule', 'unit', 'evidence_digest')}
        entry['reason'] = 'Protocol compatibility requires this local structure.'
        entry.update(changes)
        path = self.root / 'ignore.toml'
        path.write_text('[[ignore]]\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in entry.items()))
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / 'complexity.py'), *args], capture_output=True, text=True, timeout=30)

    def test_real_lizard_and_inventory(self):
        report = self.report()
        self.assertEqual(report['analysis_status'], 'complete')
        row = next(r for r in report['observations'] if r['unit'].startswith('f('))
        self.assertEqual(row['metrics']['cognitive_complexity'], 3)
        self.assertEqual(row['metrics']['cyclomatic_complexity'], 3)
        self.assertEqual(row['metrics']['parameter_count'], 1)
        self.assertEqual(len(report['findings']), 2)
        self.assertEqual(report['summary']['warnings'], 0)
        self.assertEqual(report['semantic_status'], 'not_evaluated')

    def test_ratchet_and_warning_exit_policy(self):
        self.source.write_text('int f(int x) { if (x) return 1; return 0; }\n')
        old = self.report()
        self.source.write_text('int f(int x) { if (x) { if (x > 2) return 1; } return 0; }\n')
        report = self.report(old)
        self.assertEqual(report['summary']['warnings'], 2)
        self.assertTrue(all(f['status'] == 'worsened' for f in report['findings']))
        self.config['quality_policy'] = 'fail'
        self.assertEqual(common.finalize(report, report['findings'], self.config, None), 1)
        self.assertEqual(self.report(report)['summary']['warnings'], 0)

    def test_threshold_equality_not_warning(self):
        self.config['structural']['thresholds']['cognitive_complexity'] = 3
        self.config['structural']['thresholds']['cyclomatic_complexity'] = 3
        self.assertEqual(self.report()['findings'], [])

    def test_moved_function_matches_without_line_number(self):
        old = self.report()
        self.source.rename(self.root / 'bbt/moved.cc')
        report = self.report(old)
        self.assertEqual(report['summary']['warnings'], 0)
        self.assertEqual(report['unmatched_baseline'], [])

    def test_formatting_keeps_fingerprint_but_code_change_invalidates_ignore(self):
        old = self.report()
        self.source.write_text('\n\nint f(int x) {  if (x) { if (x > 2) return 1; } return 0; } // note\n')
        current = self.report(old)
        finding = current['findings'][0]
        self.assertEqual(finding['evidence_digest'], old['findings'][0]['evidence_digest'])
        ignore = self.ignore_file(finding)
        common.apply_ignores(current['findings'], ignore)
        self.assertEqual(finding['ignore_status'], 'accepted')
        self.source.write_text(self.source.read_text().replace('> 2', '> 4'))
        current = self.report(old)
        common.apply_ignores(current['findings'], ignore)
        self.assertEqual(current['findings'][0]['ignore_status'], 'needs_review')

    def test_expired_and_invalid_ignore(self):
        findings = self.report()['findings']
        ignore = self.ignore_file(findings[0], expires_on=str(date.today() - timedelta(days=1)))
        common.apply_ignores(findings, ignore)
        self.assertEqual(findings[0]['ignore_status'], 'needs_review')
        self.ignore_file(findings[0], reason=' ')
        with self.assertRaises(common.AnalysisError):
            common.apply_ignores(findings, ignore)

    def test_config_is_strict(self):
        path = self.root / 'config.toml'
        for content in ('unknown = true', '[semantic]\nconfirmations = 0', '[structural.thresholds]\nnloc = true'):
            path.write_text(content)
            with self.assertRaises(common.AnalysisError):
                common.config_load(path)

    def test_scope_globs(self):
        self.assertTrue(structural.glob_match('bbt/f.cc', 'bbt/**/*.cc'))
        self.assertTrue(structural.glob_match('bbt/a/b/f.cc', 'bbt/**/*.cc'))
        self.assertFalse(structural.glob_match('bbt/a/b/f.cc', 'bbt/*.cc'))

    def test_budget_and_no_sources_are_not_success(self):
        self.config['limits']['max_files'] = 1
        report = self.report()
        self.assertEqual(report['analysis_status'], 'partial')
        self.assertEqual(common.finalize(report, report['findings'], self.config, None), 2)
        self.config['scope']['include'] = ['absent/**/*.cc']
        self.assertEqual(self.report()['analysis_status'], 'partial')

    def test_scope_and_version_changes_are_not_comparable(self):
        old = self.report()
        old['evaluator']['version'] = 'old'
        report = self.report(old)
        self.assertEqual(report['comparison_status'], 'not_comparable')
        self.assertEqual(report['summary']['warnings'], 0)

    def test_semantic_two_round_increment_and_json_baseline(self):
        packet = self.packet()
        old, code = self.semantic_report(packet, self.reviews(packet, 1))
        self.assertEqual(code, 0)
        old = json.loads(json.dumps(old))
        report, code = self.semantic_report(packet, self.reviews(packet, 2), old)
        self.assertEqual(code, 0)
        self.assertEqual(report['summary']['warnings'], 1)
        self.assertEqual(report['findings'][0]['warning_axes'], ['U'])
        self.assertEqual(report['findings'][0]['levels']['U'], 2)
        self.assertEqual(report['findings'][0]['status'], 'corroborated')

    def test_semantic_disagreement_unknown_and_missing_round(self):
        packet = self.packet()
        for value in (None, 1):
            reviews = self.reviews(packet)
            reviews['rounds'][1]['findings'][0]['levels']['U'] = value
            report, code = self.semantic_report(packet, reviews)
            self.assertEqual(report['summary']['warnings'], 0)
            self.assertIsNone(report['findings'][0]['levels']['U'])
            self.assertEqual(code, 2)
        reviews = self.reviews(packet)
        reviews['rounds'].pop()
        self.assertEqual(self.semantic_report(packet, reviews)[1], 2)

    def test_semantic_stale_and_fabricated_evidence_rejected(self):
        packet = self.packet()
        reviews = self.reviews(packet)
        reviews['rounds'][0]['findings'][0]['evidence'][0]['quote'] = 'not in source'
        with self.assertRaises(common.AnalysisError):
            self.semantic_report(packet, reviews)
        self.source.write_text(self.source.read_text() + '// contract change\n')
        with self.assertRaises(common.AnalysisError):
            self.semantic_report(packet, self.reviews(packet))

    def test_semantic_new_root_and_disabled_dimension(self):
        packet = self.packet()
        reviews = self.reviews(packet)
        empty = copy.deepcopy(reviews)
        for r in empty['rounds']:
            r['findings'] = []
        old, _ = self.semantic_report(packet, empty)
        report, _ = self.semantic_report(packet, reviews, old)
        self.assertEqual(report['summary']['warnings'], 1)
        self.config['semantic']['axes']['U']['enabled'] = False
        report, _ = self.semantic_report(packet, reviews, old)
        self.assertEqual(report['summary']['warnings'], 0)

    def test_uncertain_root_does_not_hide_other_root(self):
        packet = self.packet()
        old, _ = self.semantic_report(packet, self.reviews(packet, 1))
        reviews = self.reviews(packet, 2)
        for r in reviews['rounds']:
            f = copy.deepcopy(r['findings'][0])
            f['root_cause'] = 'aaa-unknown'
            f['levels']['U'] = None
            r['findings'].append(f)
        report, _ = self.semantic_report(packet, reviews, old)
        self.assertEqual(report['summary']['warnings'], 1)

    def test_bad_paths_and_missing_context(self):
        with self.assertRaises(common.AnalysisError):
            common.safe_path(self.root, '../escape.cc')
        (self.root / 'bbt/link.cc').symlink_to(self.source)
        with self.assertRaises(common.AnalysisError):
            common.safe_path(self.root, 'bbt/link.cc')
        packet = semantic.prepare(self.root, 'f', 'scenario', {'implementation': ['bbt/sample.cc']}, self.config)
        self.assertEqual(self.semantic_report(packet, self.reviews(packet))[1], 2)

    def test_cli_scan_output_protection_and_invalid_base(self):
        output = self.root / 'report.json'
        args = ['scan', '--root', str(self.root), '--output', str(output)]
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = output.read_bytes()
        self.assertEqual(self.cli(*args).returncode, 2)
        self.assertEqual(data, output.read_bytes())
        self.assertEqual(self.cli('scan', '--root', str(self.root), '--base', 'missing').returncode, 2)

    def test_cli_semantic_pipeline(self):
        packet_path = self.root / 'packet.json'
        result = self.cli('prepare', '--root', str(self.root), '--unit', 'f', '--scenario', 'Call f',
                          '--file', 'bbt/sample.cc', '--consumer', 'bbt/caller.cc', '--contract', 'contract.md',
                          '--output', str(packet_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(packet_path.read_text())
        review_path = self.root / 'reviews.json'
        review_path.write_text(json.dumps(self.reviews(packet)))
        result = self.cli('score', '--root', str(self.root), '--packet', str(packet_path), '--reviews', str(review_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['findings'][0]['levels']['U'], 2)

    def test_template_specializations_keep_separate_measurements(self):
        self.source.write_text('template<class T> class Box;\n'
                               'template<> class Box<int> { int f() { return 1; } };\n'
                               'template<> class Box<void> { int f() { return 0; } };\n')
        old = self.report()
        self.assertEqual(old['analysis_status'], 'complete')
        rows = [r for r in old['observations'] if r['path'] == 'bbt/sample.cc']
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['unit'], rows[1]['unit'])
        self.assertEqual(self.report(old)['unmatched_baseline'], [])

    def test_identical_ambiguous_definitions_are_reported_not_dropped(self):
        self.source.write_text('template<class T> class Box;\n'
                               'template<> class Box<int> {\nint f() { return 1; }\n};\n'
                               'template<> class Box<void> {\nint f() { return 1; }\n};\n')
        report = self.report()
        self.assertEqual(report['analysis_status'], 'partial')
        self.assertIn('Identical ambiguous', report['coverage']['skipped'][0]['reason'])

    def test_partial_baseline_rejected_and_github_escape(self):
        path = self.root / 'baseline.json'
        report = self.report()
        report['analysis_status'] = 'partial'
        path.write_text(json.dumps(report))
        with self.assertRaises(common.AnalysisError):
            common.baseline_load(path, report)
        report['findings'][0]['warning'] = True
        report['findings'][0]['unit'] = 'f\n::error::forged'
        annotation = complexity.github(report)
        self.assertNotIn('\n::error::forged', annotation)
        self.assertIn('%0A', annotation)


if __name__ == '__main__':
    unittest.main()
