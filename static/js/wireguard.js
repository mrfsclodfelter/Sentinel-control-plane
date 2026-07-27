function formatHandshake(ts){
  if (!ts) return 'Never';
  const seconds = Math.floor(Date.now() / 1000) - ts;
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function formatBytes(bytes){
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

async function loadPeers(){
  const res = await fetch('/api/wireguard/peers');
  const data = await res.json();
  const body = document.getElementById('wg-peers-body');
  if (!data.ok) {
    body.innerHTML = `<tr><td colspan="5" class="alert warn">${data.error || 'Could not load peers'}</td></tr>`;
    return;
  }
  body.innerHTML = (data.peers || []).map(p => `
    <tr>
      <td>${p.name}</td>
      <td class="mono">${(p.allowed_ips || '-').split('/')[0]}</td>
      <td><span class="led ${p.connected ? 'online' : 'offline'}">${p.connected ? 'CONNECTED' : 'NEVER CONNECTED'}</span></td>
      <td class="muted">${formatHandshake(p.latest_handshake)}</td>
      <td class="mono">${formatBytes(p.rx_bytes)} / ${formatBytes(p.tx_bytes)}</td>
    </tr>`).join('') || '<tr><td colspan="5" class="muted">No peers configured.</td></tr>';
}
loadPeers();

document.getElementById('wg-generate-btn').addEventListener('click', async () => {
  const input = document.getElementById('wg-new-name');
  const name = input.value.trim();
  if (!name) return;

  const btn = document.getElementById('wg-generate-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';

  try {
    const res = await fetch('/api/wireguard/peers', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name}),
    });
    const data = await res.json();
    if (!data.ok) { alert(data.error || 'Could not generate peer'); return; }

    const result = document.getElementById('wg-new-peer-result');
    result.style.display = 'block';
    result.innerHTML = `
      <div class="table-card" style="padding:18px;display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;">
        <img src="data:image/png;base64,${data.qr_code_base64}" alt="WireGuard QR code" style="width:220px;height:220px;border-radius:12px;background:#fff;padding:10px;">
        <div style="flex:1;min-width:280px;">
          <h3 style="margin:0 0 6px;">${data.peer.name} - ${data.peer.address}</h3>
          <p class="muted" style="font-size:12px;margin:0 0 10px;">Scan this with the WireGuard app, or download the config below. This is the only time the private key is shown.</p>
          <pre style="max-height:200px;overflow:auto;">${data.peer.config_text}</pre>
          <button type="button" class="small-button" id="wg-download-conf">Download .conf</button>
        </div>
      </div>`;
    document.getElementById('wg-download-conf').addEventListener('click', () => {
      const blob = new Blob([data.peer.config_text], {type: 'text/plain'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${data.peer.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-sentinel.conf`;
      a.click();
      URL.revokeObjectURL(url);
    });

    input.value = '';
    loadPeers();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Peer';
  }
});
