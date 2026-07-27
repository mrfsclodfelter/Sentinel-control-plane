let activeScenario = null;
let pastScenarios = [];

function fmtTime(ts){
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
}

function fmtDuration(startTs, endTs){
  const end = endTs || (Date.now() / 1000);
  const minutes = Math.max(0, (end - startTs) / 60);
  return minutes.toFixed(1) + ' min';
}

async function loadScenarios(){
  const res = await fetch('/api/scenarios');
  const data = await res.json();
  activeScenario = data.active || null;
  pastScenarios = (data.scenarios || []).filter(s => s.status !== 'active');
  render();
}

function render(){
  document.getElementById('scenario-active-panel').style.display = activeScenario ? 'block' : 'none';
  document.getElementById('scenario-new-panel').style.display = activeScenario ? 'none' : 'block';

  if (activeScenario) {
    document.getElementById('active-scenario-name').textContent = activeScenario.name;
    document.getElementById('active-scenario-meta').textContent =
      `${activeScenario.scenario_type || 'Unspecified type'} · started ${fmtTime(activeScenario.started_at)} · running ${fmtDuration(activeScenario.started_at)}` +
      (activeScenario.time_limit_minutes ? ` · auto-stops after ${activeScenario.time_limit_minutes} min` : '');

    const eventsEl = document.getElementById('active-scenario-events');
    const notesAsEvents = (activeScenario.manual_notes || []).map(n => ({time: n.time, message: `Analyst note: ${n.note}`}));
    const events = (activeScenario.events || []).concat(notesAsEvents).sort((a, b) => b.time - a.time);
    eventsEl.innerHTML = events.length
      ? events.map(e => `<div style="border-bottom:1px solid rgba(69,200,255,.12);padding:6px 0;"><span class="mono muted">${fmtTime(e.time)}</span> — ${e.message}</div>`).join('')
      : '<div class="muted">No activity captured yet.</div>';
  }

  const historyEl = document.getElementById('scenario-history-list');
  historyEl.innerHTML = '';
  if (!pastScenarios.length) {
    historyEl.innerHTML = '<div class="alert warn">No completed scenarios yet.</div>';
  }
  pastScenarios.forEach(s => {
    historyEl.innerHTML += `<article class="device-card hover-card">
      <div class="device-top"><h3>${s.name}</h3><span class="led online">COMPLETE</span></div>
      <div class="muted">${s.scenario_type || 'Unspecified type'}</div>
      <div class="mono">${fmtTime(s.started_at)} · ${fmtDuration(s.started_at, s.ended_at)} · ${s.events.length} events</div>
      <div class="vm-action-row">
        <a class="small-button" href="/api/scenarios/${s.id}/report.md">Download Report</a>
      </div>
    </article>`;
  });
}

document.getElementById('scenario-start-btn').addEventListener('click', async () => {
  const name = document.getElementById('scenario-name').value.trim();
  if (!name) { alert('Scenario name is required.'); return; }
  const machines = Array.from(document.querySelectorAll('.scenario-machine-checkbox:checked')).map(el => el.value);
  const timeLimit = document.getElementById('scenario-time-limit').value;

  try {
    const res = await fetch('/api/scenarios/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name,
        scenario_type: document.getElementById('scenario-type').value.trim(),
        machines,
        time_limit_minutes: timeLimit ? Number(timeLimit) : null,
      }),
    });
    const data = await res.json();
    if (!data.ok) { alert(data.error); return; }
    loadScenarios();
  } catch (e) { alert(e.message); }
});

document.getElementById('scenario-stop-btn').addEventListener('click', async () => {
  if (!activeScenario) return;
  if (!confirm('Stop this scenario? The report will be finalized.')) return;
  await fetch(`/api/scenarios/${activeScenario.id}/stop`, {method: 'POST'});
  loadScenarios();
});

document.getElementById('scenario-note-btn').addEventListener('click', async () => {
  if (!activeScenario) return;
  const input = document.getElementById('scenario-note-input');
  const note = input.value.trim();
  if (!note) return;
  await fetch(`/api/scenarios/${activeScenario.id}/note`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({note}),
  });
  input.value = '';
  loadScenarios();
});

loadScenarios();
setInterval(loadScenarios, 5000);
