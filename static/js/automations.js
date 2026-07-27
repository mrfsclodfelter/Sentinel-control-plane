let automations = [];
let hueScenes = [];
let musicTracks = [];

async function postJSON(url, payload, method){
  const res = await fetch(url, {
    method: method || 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload || {}),
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || 'Request failed');
  return data;
}

async function loadOptions(){
  try {
    const [scenesRes, tracksRes] = await Promise.all([
      fetch('/api/hue/scenes').then(r => r.json()),
      fetch('/api/music/tracks').then(r => r.json()),
    ]);
    hueScenes = scenesRes.scenes || [];
    musicTracks = tracksRes.tracks || [];

    const sceneSelect = document.getElementById('automation-hue-scene');
    sceneSelect.innerHTML = '<option value="">No change</option>' + hueScenes.map(s => `<option value="${s.name}">${s.name}</option>`).join('');

    const trackSelect = document.getElementById('automation-music-track');
    trackSelect.innerHTML = '<option value="">No track selected</option>' + musicTracks.map(t => `<option value="${t.file}">${t.name}</option>`).join('');
  } catch (e) {}
}

async function loadAutomations(){
  const res = await fetch('/api/automations');
  const data = await res.json();
  automations = data.automations || [];
  renderAutomations();
}

function summarizeActions(a){
  const parts = [];
  if (a.hue_scene) parts.push(`<li>Hue scene <span class="mono">${a.hue_scene}</span></li>`);
  if (a.music_behavior === 'play' && a.music_track) parts.push(`<li>Play <span class="mono">${a.music_track}</span> (then: ${a.after_track})</li>`);
  if (a.music_behavior === 'stop') parts.push(`<li>Stop music</li>`);
  if (a.spoken_response) parts.push(`<li>Speak: "${a.spoken_response}" <small class="muted">(pending voice link)</small></li>`);
  return parts.join('') || '<li class="muted">No actions configured</li>';
}

function renderAutomations(){
  const grid = document.getElementById('automations-list');
  grid.innerHTML = '';
  if (!automations.length) {
    grid.innerHTML = '<div class="alert warn">No automations yet - build one below.</div>';
    return;
  }
  automations.forEach(a => {
    const triggerPills = (a.voice_triggers || []).map(t => `<span class="status-pill" style="margin:2px;">${t}</span>`).join('');
    grid.innerHTML += `<article class="device-card hover-card">
      <div class="device-top">
        <div>
          <div class="eyebrow">${a.category}</div>
          <h3>${a.name}</h3>
        </div>
        <span class="led ${a.enabled ? 'online' : 'disabled'}">${a.enabled ? 'ENABLED' : 'DISABLED'}</span>
      </div>
      <div class="muted">${a.description || ''}</div>
      ${triggerPills ? `<div class="section-title" style="font-size:11px;margin:10px 0 4px;">Voice Triggers</div><div>${triggerPills}</div>` : ''}
      <div class="section-title" style="font-size:11px;margin:10px 0 4px;">Actions</div>
      <ul style="margin:0 0 10px;padding-left:18px;">${summarizeActions(a)}</ul>
      <div class="vm-action-row">
        <button type="button" class="small-button" data-run="${a.id}">Run</button>
        <button type="button" class="small-button" data-edit="${a.id}">Edit</button>
        <button type="button" class="small-button" data-toggle="${a.id}" data-enabled="${a.enabled}">${a.enabled ? 'Disable' : 'Enable'}</button>
        <button type="button" class="small-button danger-soft" data-delete="${a.id}">Delete</button>
      </div>
    </article>`;
  });
}

function updateJsonPreview(){
  const preview = document.getElementById('automation-json-preview');
  preview.textContent = JSON.stringify(collectFormValues(), null, 2);
}

function collectFormValues(){
  return {
    name: document.getElementById('automation-name').value.trim(),
    category: document.getElementById('automation-category').value.trim() || 'custom',
    enabled: document.getElementById('automation-enabled').value === 'true',
    description: document.getElementById('automation-description').value.trim(),
    voice_triggers: document.getElementById('automation-voice-triggers').value,
    natural_phrases: document.getElementById('automation-natural-phrases').value,
    spoken_response: document.getElementById('automation-spoken-response').value.trim(),
    alternate_responses: document.getElementById('automation-alt-responses').value,
    hue_scene: document.getElementById('automation-hue-scene').value,
    music_behavior: document.getElementById('automation-music-behavior').value,
    music_track: document.getElementById('automation-music-track').value,
    after_track: document.getElementById('automation-after-track').value,
  };
}

function resetEditor(){
  document.getElementById('automation-id').value = '';
  document.getElementById('automation-name').value = '';
  document.getElementById('automation-category').value = 'custom';
  document.getElementById('automation-enabled').value = 'true';
  document.getElementById('automation-description').value = '';
  document.getElementById('automation-voice-triggers').value = '';
  document.getElementById('automation-natural-phrases').value = '';
  document.getElementById('automation-spoken-response').value = '';
  document.getElementById('automation-alt-responses').value = '';
  document.getElementById('automation-hue-scene').value = '';
  document.getElementById('automation-music-behavior').value = 'none';
  document.getElementById('automation-music-track').value = '';
  document.getElementById('automation-after-track').value = 'stop';
  document.getElementById('automation-delete').style.display = 'none';
  updateJsonPreview();
}

function loadIntoEditor(a){
  document.getElementById('automation-id').value = a.id;
  document.getElementById('automation-name').value = a.name;
  document.getElementById('automation-category').value = a.category || 'custom';
  document.getElementById('automation-enabled').value = a.enabled ? 'true' : 'false';
  document.getElementById('automation-description').value = a.description || '';
  document.getElementById('automation-voice-triggers').value = (a.voice_triggers || []).join('\n');
  document.getElementById('automation-natural-phrases').value = (a.natural_phrases || []).join('\n');
  document.getElementById('automation-spoken-response').value = a.spoken_response || '';
  document.getElementById('automation-alt-responses').value = (a.alternate_responses || []).join('\n');
  document.getElementById('automation-hue-scene').value = a.hue_scene || '';
  document.getElementById('automation-music-behavior').value = a.music_behavior || 'none';
  document.getElementById('automation-music-track').value = a.music_track || '';
  document.getElementById('automation-after-track').value = a.after_track || 'stop';
  document.getElementById('automation-delete').style.display = 'inline-block';
  updateJsonPreview();
}

document.getElementById('automation-new').addEventListener('click', () => {
  resetEditor();
  document.getElementById('automation-editor-anchor').scrollIntoView({behavior: 'smooth'});
});

document.getElementById('automation-json-toggle').addEventListener('click', (e) => {
  const pre = document.getElementById('automation-json-preview');
  const visible = pre.style.display !== 'none';
  pre.style.display = visible ? 'none' : 'block';
  e.target.textContent = (visible ? '▸' : '▾') + ' Advanced action preview (read-only)';
  if (!visible) updateJsonPreview();
});

document.querySelectorAll('#automation-editor-anchor ~ .table-card input, #automation-editor-anchor ~ .table-card select, #automation-editor-anchor ~ .table-card textarea').forEach(el => {
  el.addEventListener('input', updateJsonPreview);
});

document.getElementById('automations-list').addEventListener('click', async (e) => {
  const run = e.target.closest('[data-run]');
  const edit = e.target.closest('[data-edit]');
  const del = e.target.closest('[data-delete]');
  const toggle = e.target.closest('[data-toggle]');

  try {
    if (run) {
      const data = await postJSON('/api/automations/run', {id: run.dataset.run});
      alert(data.ok ? 'Automation ran successfully.' : 'Automation ran with warnings - check console/log.');
    }
    if (edit) {
      const a = automations.find(x => x.id === edit.dataset.edit);
      if (!a) return;
      loadIntoEditor(a);
      document.getElementById('automation-editor-anchor').scrollIntoView({behavior: 'smooth'});
    }
    if (toggle) {
      const enabled = toggle.dataset.enabled !== 'true';
      await postJSON(`/api/automations/manage/${toggle.dataset.toggle}/enabled`, {enabled});
      loadAutomations();
    }
    if (del) {
      if (!confirm('Delete this automation?')) return;
      await fetch(`/api/automations/manage/${del.dataset.delete}`, {method: 'DELETE'});
      loadAutomations();
    }
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById('automation-delete').addEventListener('click', async () => {
  const id = document.getElementById('automation-id').value.trim();
  if (!id || !confirm('Delete this automation?')) return;
  await fetch(`/api/automations/manage/${id}`, {method: 'DELETE'});
  resetEditor();
  loadAutomations();
});

document.getElementById('automation-save').addEventListener('click', async () => {
  const values = collectFormValues();
  if (!values.name) { alert('Automation name is required.'); return; }

  const id = document.getElementById('automation-id').value.trim();
  try {
    const url = id ? `/api/automations/manage/${id}` : '/api/automations/manage';
    const data = await postJSON(url, values);
    loadIntoEditor(data.automation);
    loadAutomations();
    alert('Automation saved.');
  } catch (err) {
    alert(err.message);
  }
});

(async function init(){
  await loadOptions();
  resetEditor();
  await loadAutomations();
})();
