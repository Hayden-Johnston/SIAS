"""Optional browser checks: uv run --with playwright pytest -q tests/test_dashboard_browser.py.

Install Chromium first with: uv run --with playwright python -m playwright install chromium.
"""

import pytest
from test_dashboard import endpoint as endpoint  # noqa: PLC0414 -- shared pytest fixture
from test_dashboard import synthetic_manifest, write_manifest

from data_processing.run import rate

playwright = pytest.importorskip("playwright.sync_api")


def test_manifest_views_render(endpoint):
    with playwright.sync_playwright() as browser_tools:
        root, url = endpoint
        runs = root / 'runs'
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            page.wait_for_function("document.querySelector('#no-runs').textContent === 'No complete run manifests'")
            assert page.locator('#selected-run').is_disabled()
            assert page.locator('#detection-chart').inner_text().endswith('No defined rates')
            for index in range(3):
                record = synthetic_manifest(index)
                if index == 1:
                    record['metrics'] = {'tp': 300000, 'fp': 0, 'fn': 0, 'tn': 15000,
                        'detection': rate(300000, 300000), 'false_positive': rate(0, 15000)}
                    record['records'] = 315000
                write_manifest(runs, index, record)
            page.reload()
            page.wait_for_function("document.querySelectorAll('#metrics-history tr').length === 3")
            assert page.locator('#detection-chart svg polygon').count() == 1
            assert page.locator('#fp-chart svg circle').count() == 3
            assert page.locator('#outcome svg path').count() == 4
            assert 'Total ms' in page.locator('#run-report').inner_text()
            page.goto(url + '/#runs')
            page.locator('#metrics-history a').nth(1).click()
            assert 'run-1' in page.locator('#run-summary').inner_text()
            assert 'False positives (FP): 0' in page.locator('#outcome-counts').inner_text()
            # New runs must not silently switch the selected report on refresh.
            write_manifest(runs, 3)
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelectorAll('#metrics-history tr').length === 4")
            assert 'run-1' in page.locator('#run-summary').inner_text()
            page.locator('#theme').click()
            assert page.evaluate('document.documentElement.dataset.theme') in ('light', 'dark')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            # Undefined rates and a full-circle outcome render without NaN SVG geometry.
            record = synthetic_manifest(4)
            record['metrics'] = {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 10,
                                 'detection': rate(0, 0), 'false_positive': rate(0, 10)}
            record['stages'][0]['cached_latency_ms_mean'] = None
            record['pipeline_version'] = '<img src=x onerror=alert(1)>'
            write_manifest(runs, 4, record)
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelectorAll('#metrics-history tr').length === 5")
            page.locator('#metrics-history a').first.click()
            assert page.locator('#outcome svg circle').count() == 1
            assert page.locator('#metrics-history img').count() == 0
            assert 'NaN' not in page.locator('#fp-chart').inner_html()
            assert not errors, errors
        finally:
            browser.close()


def test_pages_and_activity(endpoint):
    import json

    root, url = endpoint
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(timezone_id='Asia/Tokyo')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            for view in ('board', 'activity', 'runs', 'metrics'):
                page.goto(f'{url}/#{view}')
                page.wait_for_function("document.querySelector('#refresh').textContent.startsWith('Updated')")
                assert page.locator(f'[data-page="{view}"]').is_visible()
                assert page.locator('main:visible').count() == 1
                page.reload()
                assert page.locator(f'[data-page="{view}"]').is_visible()
            assert page.evaluate("pacific('2026-11-04T12:00:00Z')").endswith('PST')
            assert '05:00:00' in page.evaluate("pacific('2026-07-04T12:00:00Z')")
            assert page.evaluate("pacific('2026-07-04T12:00:00Z')").endswith('PDT')
            (root / 'running').mkdir()
            (root / 'running' / 'new.json').write_text(json.dumps({
                'agent': 'future-agent', 'mode': 'review', 'ticket': '0020',
                'start': '2026-11-04T11:00:00+00:00'}))
            page.goto(url + '/#activity')
            page.wait_for_selector('#activity-chart svg')
            assert 'future-agent' in page.locator('#agent-states').inner_text()
            page.evaluate("""renderActivity({now: '2026-11-04T12:00:00Z',
              agents: [{agent: 'future-agent', state: 'running', ticket: '0020', elapsed: 3600}],
              runs: [
                {agent: 'future-agent', mode: 'work', ticket: '0019', title: 'Old ticket', start: '2026-11-04T06:00:00Z', end: '2026-11-04T07:00:00Z', exit: 1},
                {agent: 'future-agent', mode: 'review', ticket: '0020', title: 'Current ticket', start: '2026-11-04T11:00:00Z', end: null}
              ]})""")
            assert '2.00 active h' in page.locator('#agent-states').inner_text()
            assert page.locator('#activity-chart rect').count() == 2
            assert 'failed' in page.locator('#activity-chart').inner_text()
            assert 'Current ticket' in page.locator('#activity-chart title').all_text_contents()[-1]
            first_width = page.locator('#activity-chart rect').last.get_attribute('width')
            page.evaluate("renderActivity({...activityData, now: '2026-11-04T13:00:00Z'})")
            assert float(page.locator('#activity-chart rect').last.get_attribute('width')) > float(first_width)
            page.locator('#earlier').click()
            assert 'History' in page.locator('#activity-window').inner_text()
            page.locator('#zoom-out').click()
            assert page.evaluate('windowHours') == 12
            page.locator('#live').click()
            assert page.evaluate('windowHours') == 6
            assert 'Live' in page.locator('#activity-window').inner_text()
            assert not errors, errors
        finally:
            browser.close()
