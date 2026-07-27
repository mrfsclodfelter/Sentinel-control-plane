async function refreshOpsQueue(){
  try {
    const res = await fetch('/api/operations/queue');
    const data = await res.json();
    const body = document.getElementById('ops-queue-body');
    body.innerHTML = '';
    (data.items || []).forEach(item => {
      const cls = item.status === 'failed' ? 'bad' : item.status === 'submitted' ? 'ok' : '';
      body.innerHTML += `<tr><td class="mono">${new Date(item.updated_at).toLocaleString()}</td><td>${item.action}</td><td>${item.target}</td><td class="${cls}">${item.status}</td><td class="muted">${item.detail || ''}</td></tr>`;
    });
    if (!data.items || !data.items.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No operations submitted yet.</td></tr>';
    }
  } catch (e) { console.log('Operations queue refresh failed', e); }
}
refreshOpsQueue();
setInterval(refreshOpsQueue, 5000);
