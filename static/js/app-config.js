window.CERBERUS_APP_CONFIG_VERSION = "8.2.0";

async function postJSON(url, payload){
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const data = await res.json();
  if(!res.ok || !data.ok) throw new Error(data.error || 'Save failed');
  return data;
}
function bootstrap(){
  try { return JSON.parse(document.getElementById('config-bootstrap').textContent); }
  catch(e){ return {}; }
}
const cfg = bootstrap();

function setVal(id, value){ const el=document.getElementById(id); if(el) el.value = value || ''; }
function setChecked(id, value){ const el=document.getElementById(id); if(el) el.checked = !!value; }

function loadHue(){
  const h = (cfg.hue && cfg.hue.hue) || cfg.hue || {};
  setChecked('hue-enabled', h.enabled);
  setVal('hue-bridge', h.bridge_host);
  setVal('hue-username', h.username);
  setVal('hue-room', h.room_name);
  setVal('hue-light-ids', (h.light_ids || []).join(','));
}
function loadTextAreas(){
  ['proxmox','wazuh','devices'].forEach(name=>{
    const el = document.getElementById(`${name}-json`);
    if(el) el.value = JSON.stringify(cfg[name] || {}, null, 2);
  });
}
function buildHue(){
  const ids = document.getElementById('hue-light-ids').value.split(',').map(x=>x.trim()).filter(Boolean);
  return {hue: {
    enabled: document.getElementById('hue-enabled').checked,
    bridge_host: document.getElementById('hue-bridge').value.trim(),
    username: document.getElementById('hue-username').value.trim(),
    room_name: document.getElementById('hue-room').value.trim(),
    light_ids: ids
  }};
}
document.querySelectorAll('.config-tab').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('.config-tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.config-pane').forEach(x=>x.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`config-pane-${btn.dataset.configTab}`).classList.add('active');
  });
});
document.getElementById('save-hue-config')?.addEventListener('click', async()=>{
  try{ await postJSON('/api/config/hue', buildHue()); alert('Hue config saved. Restart Cerberus Ops if needed.'); }
  catch(e){ alert(e.message); }
});
document.getElementById('test-hue-status')?.addEventListener('click', async()=>{
  const res = await fetch('/api/hue/status');
  const data = await res.json();
  alert(JSON.stringify(data, null, 2).slice(0, 1600));
});
['proxmox','wazuh','devices'].forEach(name=>{
  document.getElementById(`save-${name}-config`)?.addEventListener('click', async()=>{
    try{
      const payload = JSON.parse(document.getElementById(`${name}-json`).value);
      await postJSON(`/api/config/${name}`, payload);
      alert(`${name} config saved.`);
    }catch(e){ alert(e.message); }
  });
});
loadHue();
loadTextAreas();
