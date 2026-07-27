function bootstrapScenes(){
  try { return JSON.parse(document.getElementById('hue-scenes-bootstrap').textContent); }
  catch(e){ return []; }
}
let scenes = bootstrapScenes();

const COLOR_PRESETS = [
  {name: 'Standby Blue', hex: '#1f7aff'},
  {name: 'Armed Purple', hex: '#8c4dff'},
  {name: 'Alert Yellow', hex: '#ffd24d'},
  {name: 'Critical Red', hex: '#ff2436'},
  {name: 'Complete Green', hex: '#35ff8a'},
  {name: 'Backup Cyan', hex: '#00d4ff'},
  {name: 'Orange', hex: '#ff8a3d'},
  {name: 'Pink', hex: '#ff6bb3'},
  {name: 'Warm White', hex: '#ffffff'},
];

function presetFor(hex){
  const found = COLOR_PRESETS.find(p => p.hex.toLowerCase() === String(hex || '').toLowerCase());
  return found ? found.name : 'Custom color';
}

async function postJSON(url, payload){
  const res = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload || {})});
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || 'Request failed');
  return data;
}

async function saveAllScenes(){
  const data = await postJSON('/api/hue/scenes', {scenes});
  scenes = data.scenes;
  return data;
}

function swatchRow(cardId, currentHex){
  return COLOR_PRESETS.map(p => `<span class="hue-swatch" data-card="${cardId}" data-hex="${p.hex}" title="${p.name}"
    style="display:inline-block;width:22px;height:22px;border-radius:50%;background:${p.hex};cursor:pointer;border:2px solid ${p.hex.toLowerCase() === currentHex.toLowerCase() ? '#fff' : 'transparent'};box-shadow:0 0 8px ${p.hex}88;margin-right:4px;"></span>`).join('');
}

function cardHTML(scene, index){
  const cardId = `hscene-${index}`;
  const hex = scene.color && scene.color.startsWith('#') ? scene.color : '#1f7aff';
  return `<article class="device-card hue-scene-card" id="${cardId}" data-index="${index}" style="padding:18px;">
    <div style="display:flex;gap:16px;align-items:center;margin-bottom:14px;">
      <div class="hue-preview" style="width:56px;height:56px;border-radius:50%;flex-shrink:0;background:${hex};box-shadow:0 0 26px ${hex}aa, inset 0 0 20px rgba(255,255,255,.15);"></div>
      <div style="flex:1;min-width:0;">
        <label class="field-label">Scene Name</label>
        <input class="cerb-input hs-name" value="${scene.name || ''}" placeholder="night time">
      </div>
    </div>

    <label class="field-label">Color</label>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
      <input type="color" class="hs-native-picker" value="${hex}" style="width:38px;height:34px;padding:2px;border-radius:8px;border:1px solid rgba(69,200,255,.3);background:none;cursor:pointer;flex-shrink:0;">
      <select class="cerb-input hs-preset" style="width:auto;flex:1;min-width:140px;">
        ${COLOR_PRESETS.map(p => `<option value="${p.hex}" ${p.hex.toLowerCase() === hex.toLowerCase() ? 'selected' : ''}>${p.name}</option>`).join('')}
        <option value="__custom__" ${!COLOR_PRESETS.find(p => p.hex.toLowerCase() === hex.toLowerCase()) ? 'selected' : ''}>Custom color</option>
      </select>
    </div>
    <div class="hs-swatches" style="margin-bottom:6px;">${swatchRow(cardId, hex)}</div>
    <div class="hs-hex-toggle" style="font-size:11px;color:var(--blue);cursor:pointer;margin-bottom:14px;">▸ Advanced Hex</div>
    <input class="cerb-input hs-hex" value="${hex}" style="display:none;margin-bottom:14px;width:110px;">

    <label class="field-label">Brightness</label>
    <input type="range" class="hs-brightness" min="1" max="254" value="${scene.brightness || 180}" style="width:100%;">

    <div style="display:flex;gap:14px;margin-top:10px;">
      <div>
        <label class="field-label">Transition (ms)</label>
        <input class="cerb-input hs-transition" type="number" min="0" value="${scene.transition || 700}" style="width:100px;">
      </div>
      <div>
        <label class="field-label">Effect</label>
        <select class="cerb-input hs-effect">
          <option value="static" ${scene.effect === 'static' ? 'selected' : ''}>Static</option>
          <option value="pulse" ${scene.effect === 'pulse' ? 'selected' : ''}>Pulse</option>
          <option value="colorloop" ${scene.effect === 'colorloop' ? 'selected' : ''}>Colorloop</option>
          <option value="critical" ${scene.effect === 'critical' ? 'selected' : ''}>Critical (long alert)</option>
        </select>
      </div>
      <div style="margin-left:auto;align-self:flex-end;display:flex;gap:8px;">
        <button type="button" class="small-button hs-trigger">Trigger</button>
        <button type="button" class="small-button danger-soft hs-delete">Delete</button>
      </div>
    </div>
  </article>`;
}

function renderScenes(){
  const list = document.getElementById('hue-scenes-list');
  list.innerHTML = scenes.map((s, i) => cardHTML(s, i)).join('');
}
renderScenes();

function readCard(card){
  const index = Number(card.dataset.index);
  return {
    index,
    name: card.querySelector('.hs-name').value.trim(),
    color: card.querySelector('.hs-hex').value.trim() || '#1f7aff',
    brightness: Number(card.querySelector('.hs-brightness').value) || 180,
    transition: Number(card.querySelector('.hs-transition').value) || 700,
    effect: card.querySelector('.hs-effect').value,
  };
}

function updatePreview(card){
  const hex = card.querySelector('.hs-hex').value.trim() || '#1f7aff';
  card.querySelector('.hue-preview').style.background = hex;
  card.querySelector('.hue-preview').style.boxShadow = `0 0 26px ${hex}aa, inset 0 0 20px rgba(255,255,255,.15)`;
  card.querySelectorAll('.hue-swatch').forEach(sw => {
    sw.style.border = sw.dataset.hex.toLowerCase() === hex.toLowerCase() ? '2px solid #fff' : '2px solid transparent';
  });
  const preset = card.querySelector('.hs-preset');
  const match = COLOR_PRESETS.find(p => p.hex.toLowerCase() === hex.toLowerCase());
  preset.value = match ? match.hex : '__custom__';
  const nativePicker = card.querySelector('.hs-native-picker');
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) nativePicker.value = hex;
}

document.getElementById('hue-scene-new').addEventListener('click', () => {
  scenes.push({name: 'new scene', color: '#1f7aff', brightness: 180, transition: 700, effect: 'static'});
  renderScenes();
  document.getElementById(`hscene-${scenes.length - 1}`).scrollIntoView({behavior: 'smooth'});
});

document.getElementById('hue-scenes-list').addEventListener('click', async (e) => {
  const card = e.target.closest('.hue-scene-card');
  if (!card) return;
  const index = Number(card.dataset.index);

  if (e.target.classList.contains('hue-swatch')) {
    const hex = e.target.dataset.hex;
    card.querySelector('.hs-hex').value = hex;
    updatePreview(card);
    scenes[index] = readCard(card);
    try { await saveAllScenes(); } catch (err) { alert(err.message); }
    return;
  }
  if (e.target.classList.contains('hs-hex-toggle')) {
    const hexInput = card.querySelector('.hs-hex');
    const visible = hexInput.style.display !== 'none';
    hexInput.style.display = visible ? 'none' : 'block';
    e.target.textContent = (visible ? '▸' : '▾') + ' Advanced Hex';
    return;
  }
  if (e.target.classList.contains('hs-trigger')) {
    try { await postJSON(`/api/hue/scene/${encodeURIComponent(scenes[index].name)}/trigger`); }
    catch (err) { alert(err.message); }
    return;
  }
  if (e.target.classList.contains('hs-delete')) {
    if (!confirm(`Delete scene "${scenes[index].name}"?`)) return;
    scenes.splice(index, 1);
    try { await saveAllScenes(); renderScenes(); } catch (err) { alert(err.message); }
    return;
  }
});

document.getElementById('hue-scenes-list').addEventListener('change', async (e) => {
  const card = e.target.closest('.hue-scene-card');
  if (!card) return;
  const index = Number(card.dataset.index);

  if (e.target.classList.contains('hs-preset')) {
    if (e.target.value !== '__custom__') {
      card.querySelector('.hs-hex').value = e.target.value;
      updatePreview(card);
    }
  }
  if (e.target.classList.contains('hs-hex') || e.target.classList.contains('hs-native-picker')) {
    if (e.target.classList.contains('hs-native-picker')) card.querySelector('.hs-hex').value = e.target.value;
    updatePreview(card);
  }

  scenes[index] = readCard(card);
  try { await saveAllScenes(); } catch (err) { alert(err.message); }
});

document.getElementById('hue-scenes-list').addEventListener('input', (e) => {
  const card = e.target.closest('.hue-scene-card');
  if (!card) return;
  if (e.target.classList.contains('hs-hex')) updatePreview(card);
  if (e.target.classList.contains('hs-native-picker')) {
    card.querySelector('.hs-hex').value = e.target.value;
    updatePreview(card);
  }
});

document.getElementById('hue-scenes-list').addEventListener('blur', async (e) => {
  const card = e.target.closest('.hue-scene-card');
  if (!card || !e.target.classList.contains('hs-name')) return;
  const index = Number(card.dataset.index);
  scenes[index] = readCard(card);
  try { await saveAllScenes(); } catch (err) { alert(err.message); }
}, true);
