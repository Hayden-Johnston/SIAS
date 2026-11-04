// Agent metadata only. Pan and zoom keep a fixed window until Live is selected.
let activityData, windowHours = 6, windowEnd = null;
const agentColor = agent => {
  const known = {claude: '#0072b2', codex: '#009e73', pi: '#cc79a7'};
  let hash = 0;
  for (const char of agent) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return known[agent] || ['#e69f00', '#56b4e9', '#d55e00', '#0072b2', '#009e73', '#cc79a7'][hash % 6];
};
function renderActivity(data) {
  activityData = data;
  const now = Date.parse(data.now), end = windowEnd ?? now, start = end - windowHours * 3600000;
  const x = time => 160 + (time - start) / (end - start) * 800;
  const states = document.querySelector('#agent-states'); states.replaceChildren();
  const chart = document.querySelector('#activity-chart'); chart.replaceChildren();
  document.querySelector('#activity-window').textContent = `${pacific(start)} – ${pacific(end)} · ${windowEnd === null ? 'Live' : 'History'}`;
  if (!data.agents.length) { states.append(el('p', 'No agent runs recorded', 'muted')); return; }
  const svg = svgNode('svg', {class: 'activity-plot', viewBox: `0 0 1000 ${data.agents.length * 100 + 80}`, role: 'img', 'aria-label': 'Agent activity timeline in Pacific time'});
  for (let tick = 0; tick <= 4; tick++) {
    const time = start + (end - start) * tick / 4;
    svg.append(svgNode('line', {x1: x(time), x2: x(time), y1: 45, y2: data.agents.length * 100 + 45, stroke: 'var(--line)'}));
    svg.append(svgNode('text', {x: x(time), y: 20, 'text-anchor': tick === 0 ? 'start' : tick === 4 ? 'end' : 'middle'}, new Intl.DateTimeFormat('en-US', {timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'}).format(time)));
  }
  data.agents.forEach((agent, index) => {
    const color = agentColor(agent.agent), y = 75 + index * 100;
    const intervals = data.runs.filter(run => run.agent === agent.agent).map(run => ({run, from: Math.max(start, Date.parse(run.start)), to: Math.min(end, Date.parse(run.end || data.now))})).filter(r => r.to > r.from).sort((a, b) => a.from - b.from);
    // Union intervals so duplicate/overlapping records cannot inflate active hours.
    let active = 0, through = start;
    for (const interval of intervals) { active += Math.max(0, interval.to - Math.max(through, interval.from)); through = Math.max(through, interval.to); }
    const status = agent.state === 'running' ? `running ticket ${agent.ticket} for ${Math.floor(agent.elapsed / 60)} min` : agent.state === 'capped' ? `capped until ${pacific(agent.until)}` : agent.state;
    const line = el('p'); const swatch = el('span', '', 'swatch'); swatch.style.backgroundColor = color;
    line.append(swatch, el('span', `${agent.agent} · ${status} · ${(active / 3600000).toFixed(2)} active h in window`)); states.append(line);
    svg.append(svgNode('text', {x: 10, y: y + 18}, agent.agent));
    for (const {run, from, to} of intervals) {
      const group = svgNode('g');
      const exit = run.end ? (run.exit === 0 ? 'ok' : 'failed') : 'running';
      const duration = Math.max(0, (Date.parse(run.end || data.now) - Date.parse(run.start)) / 60000);
      group.append(svgNode('title', {}, `${run.title || 'No ticket title'} · #${run.ticket} · ${run.mode} · ${duration.toFixed(1)} min · exit ${run.exit ?? '—'} (${exit}) · ${pacific(run.start)} – ${pacific(run.end || data.now)}`));
      group.append(svgNode('rect', {x: x(from), y, width: Math.max(1, x(to) - x(from)), height: 28, fill: color, opacity: .8}));
      if (Date.parse(run.start) >= start) group.append(svgNode('text', {x: x(from), y: y - 8}, `#${run.ticket} · ${run.mode}`));
      if (run.end && Date.parse(run.end) <= end) {
        group.append(svgNode('line', {x1: x(to), x2: x(to), y1: y - 3, y2: y + 31, stroke: 'var(--ink)', 'stroke-width': 2}));
        group.append(svgNode('text', {x: x(to), y: y + 46, 'text-anchor': 'end'}, exit));
      }
      svg.append(group);
    }
  });
  chart.append(svg);
}
for (const [id, shift] of [['earlier', -1], ['later', 1]]) document.getElementById(id).onclick = () => {
  if (!activityData) return;
  windowEnd = Math.min(Date.parse(activityData.now), (windowEnd ?? Date.parse(activityData.now)) + shift * windowHours * 3600000 / 2);
  renderActivity(activityData);
};
for (const [id, factor] of [['zoom-in', .5], ['zoom-out', 2]]) document.getElementById(id).onclick = () => {
  windowHours = Math.max(.25, Math.min(24 * 365, windowHours * factor));
  if (activityData) renderActivity(activityData);
};
document.querySelector('#live').onclick = () => { windowEnd = null; windowHours = 6; if (activityData) renderActivity(activityData); };
