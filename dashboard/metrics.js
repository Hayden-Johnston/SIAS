// UTC stays in the API; every displayed timestamp uses Pacific, including DST labels.
const pacific = value => new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'}).format(new Date(value));
// Manifest aggregates only; all labels use textContent, never HTML interpolation.
const metricColors = {tp: '#0072b2', fp: '#e69f00', fn: '#d55e00', tn: '#009e73'};
const percent = value => value == null ? '—' : `${(value * 100).toFixed(5)}%`;
const rateLabel = rate => `${percent(rate.value)} [${rate.ci95.map(percent).join('–')}]; n=${rate.n}`;
const svgNode = (tag, attributes = {}, text) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
};

function rateChart(container, runs, key, title, color, target) {
  container.replaceChildren(el('h3', title));
  const points = [...runs].reverse().filter(run => run.metrics[key].value != null);
  if (!points.length) { container.append(el('p', 'No defined rates', 'muted')); return; }
  const svg = svgNode('svg', {class: 'rate-plot', viewBox: '0 0 680 360', role: 'img', 'aria-label': `${title}: log axis, 95% confidence band`});
  svg.append(svgNode('title', {}, `${title} over time, with 95% confidence intervals`));
  // Seven decades retain target-scale changes while also showing early, poor runs.
  const error = value => key === 'detection' ? 1 - value : value;
  const y = value => {
    const decades = -Math.log10(Math.max(1e-7, error(value))) / 7 * 230;
    return key === 'detection' ? 265 - decades : 35 + decades;
  };
  const times = points.map(run => Date.parse(run.timestamp));
  const first = Math.min(...times), last = Math.max(...times);
  const x = run => last === first ? 330 : 100 + (Date.parse(run.timestamp) - first) / (last - first) * 460;
  for (let exponent = 0; exponent >= -7; exponent--) {
    const value = key === 'detection' ? 1 - 10 ** exponent : 10 ** exponent;
    const height = y(value);
    svg.append(svgNode('line', {x1: 96, x2: 565, y1: height, y2: height, stroke: 'var(--line)'}));
    svg.append(svgNode('text', {x: 90, y: height + 4, 'text-anchor': 'end'}, `${exponent === -7 ? (key === 'detection' ? '≥' : '≤') : ''}${percent(value)}`));
  }
  const upper = points.map(run => `${x(run)},${y(run.metrics[key].ci95[1])}`);
  const lower = [...points].reverse().map(run => `${x(run)},${y(run.metrics[key].ci95[0])}`);
  svg.append(svgNode('polygon', {points: [...upper, ...lower].join(' '), fill: color, opacity: .18}));
  svg.append(svgNode('polyline', {points: points.map(run => `${x(run)},${y(run.metrics[key].value)}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2}));
  svg.append(svgNode('line', {x1: 96, x2: 565, y1: y(target), y2: y(target), stroke: color, 'stroke-dasharray': '6 4'}));
  svg.append(svgNode('text', {x: 570, y: y(target) - 6}, 'Target'));
  svg.append(svgNode('text', {x: 570, y: y(target) + 10}, percent(target)));
  points.forEach((run, index) => {
    const circle = svgNode('circle', {cx: x(run), cy: y(run.metrics[key].value), r: 4, fill: color});
    circle.append(svgNode('title', {}, `${run.run_id} · ${pacific(run.timestamp)} · ${rateLabel(run.metrics[key])}`));
    svg.append(circle);
    const label = svgNode('text', {x: x(run), y: 286 + (index % 3) * 22, 'text-anchor': 'middle'}, `i${run.iteration} · ${run.pipeline_version}`);
    label.append(svgNode('title', {}, `${pacific(run.timestamp)} · ${run.run_id}`));
    svg.append(label);
    svg.append(svgNode('line', {x1: x(run), x2: x(run), y1: 267, y2: 274, stroke: 'var(--ink)'}));
    // A lone run has a zero-width band, so also draw each interval explicitly.
    svg.append(svgNode('line', {x1: x(run), x2: x(run), y1: y(run.metrics[key].ci95[0]), y2: y(run.metrics[key].ci95[1]), stroke: color, 'stroke-width': 2}));
  });
  svg.append(svgNode('text', {x: 100, y: 352}, pacific(first)));
  if (last !== first) svg.append(svgNode('text', {x: 560, y: 352, 'text-anchor': 'end'}, pacific(last)));
  container.append(svg);
}

function showRun(run) {
  for (const id of ['run-summary', 'distribution', 'outcome', 'outcome-counts', 'stages']) document.getElementById(id).replaceChildren();
  if (!run) { document.querySelector('#run-summary').textContent = 'No run selected'; return; }
  document.querySelector('#run-summary').textContent = `${run.run_id} · ${run.records} records · ${run.evaluation_split} · evaluator approved: ${run.evaluator_approved ? 'yes' : 'no'} · Detection ${rateLabel(run.metrics.detection)} · False positives ${rateLabel(run.metrics.false_positive)}`;
  document.querySelector('#distribution').textContent = `Attack distribution: ${Object.entries(run.attack_distribution).map(([name, n]) => `${name}: ${n}`).join(', ') || 'No attacks'}. Rates apply to this dataset and split.`;
  const total = ['tp', 'fp', 'fn', 'tn'].reduce((sum, key) => sum + run.metrics[key], 0);
  const svg = svgNode('svg', {viewBox: '0 0 240 240', role: 'img', 'aria-label': 'Outcome proportions; counts listed below'});
  let offset = 0;
  for (const [key, name] of Object.entries({tp: 'True positives', fp: 'False positives', fn: 'False negatives', tn: 'True negatives'})) {
    const count = run.metrics[key];
    if (count && total) {
      const fraction = count / total * 100;
      const position = percent => {
        const angle = (percent / 100 * 360 - 90) * Math.PI / 180;
        return `${120 + 100 * Math.cos(angle)} ${120 + 100 * Math.sin(angle)}`;
      };
      const slice = fraction === 100 ? svgNode('circle', {cx: 120, cy: 120, r: 100, fill: metricColors[key]}) :
        svgNode('path', {d: `M120 120 L${position(offset)} A100 100 0 ${fraction > 50 ? 1 : 0} 1 ${position(offset + fraction)} Z`, fill: metricColors[key]});
      slice.append(svgNode('title', {}, `${name}: ${count}`));
      svg.append(slice); offset += fraction;
    }
    const label = el('p'); const swatch = el('span', '', 'swatch'); swatch.style.backgroundColor = metricColors[key];
    label.append(swatch, el('span', `${name} (${key.toUpperCase()}): ${count}`));
    document.querySelector('#outcome-counts').append(label);
  }
  document.querySelector('#outcome').append(total ? svg : el('p', 'No evaluated prompts', 'muted'));
  for (const stage of run.stages) {
    const row = el('tr');
    for (const value of [`${stage.name} / ${stage.version}`, stage.reached, stage.caught, stage.passed, stage.cached_latency_ms_total.toFixed(2), stage.cached_latency_ms_mean?.toFixed(2) ?? '—']) row.append(el('td', value));
    document.querySelector('#stages').append(row);
  }
}

function renderMetrics(runs) {
  const select = document.querySelector('#selected-run');
  const previous = select.selectedOptions[0]?.textContent;
  select.replaceChildren();
  const history = document.querySelector('#metrics-history'); history.replaceChildren();
  runs.forEach((run, index) => {
    // Index values keep duplicate run ids selectable without putting them in URLs.
    const option = el('option', `${run.run_id} · ${pacific(run.timestamp)}`); option.value = String(index); select.append(option);
    if (option.textContent === previous) option.selected = true;
    const row = el('tr'), cell = el('td'), link = el('a', run.run_id); link.href = '#run-report';
    link.onclick = () => { select.value = String(index); showRun(run); };
    cell.append(link); row.append(cell);
    for (const value of [pacific(run.timestamp), run.iteration, run.pipeline_version, `${run.dataset_sha256.slice(0, 12)}… / ${run.evaluation_split}`, run.records]) row.append(el('td', value));
    row.children[4].title = run.dataset_sha256;
    for (const key of ['detection', 'false_positive']) {
      const rate = run.metrics[key], cell = el('td', undefined, 'metric-rate');
      cell.append(el('p', percent(rate.value)), el('small', `[${rate.ci95.map(percent).join('–')}]; n=${rate.n}`));
      row.append(cell);
    }
    history.append(row);
  });
  document.querySelector('#no-runs').textContent = runs.length ? `${runs.length} complete runs · newest first` : 'No complete run manifests';
  rateChart(document.querySelector('#detection-chart'), runs, 'detection', 'Detection rate', metricColors.tp, .99999);
  rateChart(document.querySelector('#fp-chart'), runs, 'false_positive', 'False-positive rate', metricColors.fp, .0002);
  select.disabled = !runs.length;
  select.onchange = () => showRun(runs[Number(select.value)]);
  showRun(runs[Number(select.value)]);
}
