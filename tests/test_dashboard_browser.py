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


def test_metric_slices(endpoint):
    from data_processing.run import sliced_metrics

    root, url = endpoint
    record = synthetic_manifest()
    record['slices'] = sliced_metrics([
        {'label': 1, 'detected': False, 'channel': 'direct', 'length_bucket': '0-4096',
         'techniques': ['novel', 'encoding'], 'attack_family': '<img src=x>'},
    ])
    record['slices']['novel_technique'] = [
        {'technique': 'encoding', 'n': 1, 'small_sample': True, 'detection': rate(0, 1)}]
    write_manifest(root / 'runs', record=record)
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page()
        try:
            page.goto(url + '/#metrics')
            page.wait_for_selector('#metric-slices tr')
            assert page.locator('#metric-slices tr').count() == 5
            assert 'small sample (n<20)' in page.locator('#metric-slices').inner_text()
            assert 'n=1' in page.locator('#metric-slices').inner_text()
            assert 'encoding' in page.locator('#metric-slices').inner_text()
            assert 'novel' in page.locator('#metric-slices').inner_text()
            assert page.locator('#metric-slices img').count() == 0
            assert page.locator('#novel-techniques tr').count() == 1
            assert 'encoding' in page.locator('#novel-techniques').inner_text()
            assert 'n=1' in page.locator('#novel-techniques').inner_text()
            assert 'small sample' in page.locator('#novel-techniques').inner_text()
            record['slices']['novel_technique'] = []
            write_manifest(root / 'runs', record=record)
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelector('#no-novel-techniques').textContent.startsWith('No held-out')")
            write_manifest(root / 'runs', 1)
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelectorAll('#slice-run option').length === 2")
            assert page.locator('#metric-slices tr').count() == 5
            page.locator('#slice-run').select_option('0')
            assert page.locator('#metric-slices tr').count() == 0
            assert page.locator('#no-slices').inner_text() == 'No slice metrics in this run'
            assert 'Comparison unavailable' in page.locator('#no-novel-techniques').inner_text()
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
            for view in ('updates', 'alerts', 'board', 'activity', 'runs', 'metrics', 'recall'):
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


def test_updates_alerts_and_notifications(endpoint):
    from test_dashboard import write_ticket

    root, url = endpoint
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(timezone_id='Asia/Tokyo')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('''
            window.notices = [];
            window.Notification = class {
              static permission = 'granted';
              static requestPermission() { return Promise.resolve('granted'); }
              constructor(title, options) { window.notices.push(options); }
            };
        ''')
        try:
            page.goto(url)
            page.wait_for_function("document.querySelector('#refresh').textContent.startsWith('Updated')")
            assert page.locator('[data-page="updates"]').is_visible()
            assert not page.locator('#alert-banner').is_visible()
            page.evaluate('renderNews({alerts: [], updates: []})')
            assert page.locator('#updates').inner_text() == 'No updates in this window'
            page.locator('nav a[href="#alerts"]').click()
            assert page.locator('#alerts').inner_text() == 'No alerts'
            page.locator('#notifications').click()
            assert page.evaluate("localStorage.getItem('alert-notifications')") == 'on'
            write_ticket(root, '0001', 'blocked', logs='- 2026-11-04 10:00 codex: <img src=x>\n')
            page.evaluate('refresh()')
            page.wait_for_selector('#alerts article')
            assert page.locator('#alert-banner').is_visible()
            assert page.locator('#alerts img').count() == 0
            assert page.evaluate('notices.length') == 1
            page.evaluate('refresh()')
            page.wait_for_timeout(200)
            assert page.evaluate('notices.length') == 1
            page.reload()
            page.wait_for_selector('#alerts article')
            assert page.locator('#notifications').inner_text() == 'Disable browser notifications'
            assert page.evaluate('notices.length') == 0
            page.locator('nav a[href="#updates"]').click()
            page.locator('#load-more').click()
            page.wait_for_function("document.querySelector('#updates-window').textContent.startsWith('Last 96 hours')")
            assert not errors, errors
        finally:
            browser.close()


def test_server_activity_chart(endpoint):
    import json

    root, url = endpoint
    (root / 'servers.jsonl').write_text('\n'.join(json.dumps(row) for row in [
        {'timestamp': '2026-11-04T11:50:00Z', 'server': 'llama', 'up': True, 'models': ['model-a']},
        {'timestamp': '2026-11-04T11:55:00Z', 'server': 'llama', 'up': False, 'models': []},
    ]))
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(url + '/#activity')
            page.wait_for_selector('#server-chart svg')
            # Fix the clock independently of the machine's current time.
            page.evaluate("renderActivity({...activityData, now: '2026-11-04T12:00:00Z'})")
            assert page.locator('#server-chart rect').count() == 2
            assert 'model-a' in page.locator('#server-chart title').first.text_content()
            assert 'down' in page.locator('#server-chart title').last.text_content()
            width = float(page.locator('#server-chart rect').first.get_attribute('width'))
            page.locator('#zoom-in').click()
            assert float(page.locator('#server-chart rect').first.get_attribute('width')) > width
            page.locator('#earlier').click()
            assert page.locator('#server-chart rect').count() == 0
            page.locator('#live').click()
            assert page.locator('#server-chart rect').count() == 2
            assert not errors, errors
        finally:
            browser.close()


def test_latest_recall_page(endpoint):
    from data_processing.run import sliced_metrics

    root, url = endpoint
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page()
        try:
            page.goto(url + '/#recall')
            page.wait_for_function("document.querySelector('#no-recall').textContent === 'No complete run manifests'")
            record = synthetic_manifest()
            record['slices'] = sliced_metrics([
                {'label': 1, 'detected': False, 'channel': 'direct',
                 'length_bucket': '0-4096', 'techniques': ['encoding'],
                 'attack_family': 'synthetic-family'},
            ])
            write_manifest(root / 'runs', record=record)
            page.evaluate('refresh()')
            page.wait_for_selector('#recall-slices tr')
            assert page.locator('#recall-slices tr').count() == 2
            assert page.locator('#recall-slices tr').first.locator('td').all_text_contents() == [
                'technique', 'encoding', '1', '0', '1',
                '0.00000% [0.00000%–79.34507%]; n=1', 'small sample (n<20)']
            write_manifest(root / 'runs', 1)
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelector('#recall-summary').textContent.startsWith('run-1')")
            assert page.locator('#recall-slices tr').count() == 0
            assert page.locator('#no-recall').inner_text() == 'No technique or channel metrics in this run'
        finally:
            browser.close()


def test_stage_ablation_page(endpoint):
    import json

    from test_dashboard_ablation import sample_ablation

    root, url = endpoint
    with playwright.sync_playwright() as browser_tools:
        browser = browser_tools.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(url + '/#ablation')
            page.wait_for_function("document.querySelector('#no-ablation').textContent.startsWith('No valid')")
            assert page.locator('[data-page="ablation"]').is_visible()
            runs = root / 'runs'
            runs.mkdir()
            path = runs / 'stage-ablation.json'
            record = sample_ablation()
            path.write_text(json.dumps(record))
            page.evaluate('refresh()')
            page.wait_for_selector('#ablation-fits tr')
            assert page.locator('#ablation-fits tr').count() == 2
            assert page.locator('#ablation-fits tr').nth(1).locator('td').all_text_contents() == [
                'Without rules', '1', '1', '0', '2',
                '50.00000% [9.45312%–90.54688%]; n=2',
                '0.00000% [0.00000%–65.76198%]; n=2', '-50.00000 pp', '-50.00000 pp']
            record['removed_stages']['<img src=x>'] = record['removed_stages'].pop('rules')
            record['full']['held_out_metrics']['detection'] = rate(0, 0)
            record['removed_stages']['<img src=x>']['delta_vs_full']['detection'] = None
            path.write_text(json.dumps(record))
            page.reload()
            page.wait_for_function("document.querySelector('#ablation-fits').textContent.includes('Without <img')")
            assert page.locator('#ablation-fits img').count() == 0
            assert page.locator('#ablation-fits tr').first.locator('td').nth(5).inner_text() == '— [—–—]; n=0'
            assert page.locator('#ablation-fits tr').nth(1).locator('td').nth(7).inner_text() == '—'
            path.unlink()
            page.evaluate('refresh()')
            page.wait_for_function("document.querySelectorAll('#ablation-fits tr').length === 0")
            assert not errors, errors
        finally:
            browser.close()
