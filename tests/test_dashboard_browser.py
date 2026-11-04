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
