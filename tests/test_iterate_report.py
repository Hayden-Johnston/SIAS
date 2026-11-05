"""Edge cases for the iteration markdown report rendering in ops/iterate.py.

The report is written inline at the end of iterate.iterate, so these drive a full
iteration with synthetic data and assert the rendered file has no gaps for the
null/missing/empty states.
"""

import json

from test_iterate import run
from test_iterate import setup as setup  # noqa: PLC0414 -- shared pytest fixture


def test_report_null_slices_unavailable_stages_and_empty_red_team(setup):
    """Default run: validation slices bind no dev techniques (novel_technique null),
    the optional probe and cpu-classifier are not available, and the red-team round
    is empty. Every one of these must render without raising."""
    result = run(setup)
    assert result['probe'] == 'not available'
    assert result['cpu_classifier'] == 'not available'
    report = next(setup[2].glob('*.md')).read_text()
    assert report.startswith('# Iteration 1:')
    assert 'probe: not available' in report
    assert 'cpu-classifier: not available' in report
    assert 'Red-team round: off; generated 0, approved 0; approval rate None;' in report
    # Validation runs carry no split_manifest, so their novel-technique slice is null.
    assert '"novel_technique":null' in report


def test_report_zero_row_split(setup):
    """A zero-row scoring split must render a 0-row stage line and empty slices."""
    config_path, _data, reports = setup
    (config_path.parent / 'raw.jsonl').write_text(
        json.dumps({'text': 'synthetic attack', 'label': 1}) + '\n')
    config = json.loads(config_path.read_text())
    config['augment'] = False
    config_path.write_text(json.dumps(config))
    result = run(setup)
    assert result['split_counts']['dev']['records'] == 0
    report = next(reports.glob('*.md')).read_text()
    assert '- validation / rules: 0 rows; TP 0, FP 0, FN 0, TN 0;' in report
    assert '### validation / rules' in report
    assert '"by_technique":{}' in report
