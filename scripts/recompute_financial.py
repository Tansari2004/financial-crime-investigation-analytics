"""One-command bounded-space precision audit; preserves prior experiments."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        env[name] = '1'
    def run(*arguments):
        subprocess.run([sys.executable, *map(str, arguments)], cwd=ROOT, env=env, check=True)
    for name in ('full', 'rounded'):
        folder = args.output.resolve() / name
        command = ['scripts/rebuild_financial_bounded.py', '--source', args.source.resolve(), '--output', folder]
        if name == 'rounded':
            command.append('--rounded-control')
        run(*command)
        run('-m', 'financial_crime.train_model', '--features', folder / 'model_features.csv.gz',
            '--scores', folder / 'scores.csv.gz', '--model', folder / 'model.npz',
            '--metrics', folder / 'metrics.json', '--evaluation-scores-only')
        run('scripts/compare_financial_rules.py', '--features', folder / 'model_features.csv.gz',
            '--scores', folder / 'scores.csv.gz', '--precision-evidence', folder / 'precision_import.json',
            '--model-metrics', folder / 'metrics.json', '--output', folder / 'comparison.json')
        run('scripts/verify_financial_results.py', '--features', folder / 'model_features.csv.gz',
            '--scores', folder / 'scores.csv.gz', '--metrics', folder / 'metrics.json',
            '--comparison', folder / 'comparison.json', '--output', folder / 'independent_verification.json')
    run('scripts/compare_financial_precision.py', '--full', args.output.resolve() / 'full',
        '--rounded', args.output.resolve() / 'rounded', '--output', args.output.resolve() / 'precision_comparison.json')


if __name__ == '__main__': main()
