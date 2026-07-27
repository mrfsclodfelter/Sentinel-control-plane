function tickClock(){
  document.getElementById('wall-clock').textContent = new Date().toLocaleString();
}
tickClock();
setInterval(tickClock, 1000);

function sparkline(svgId, values){
  const svg = document.getElementById(svgId);
  if (!values || values.length < 2) {
    svg.innerHTML = '<text x="150" y="26" text-anchor="middle" fill="#5b6b85" font-size="11">Not enough data yet</text>';
    return;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);
  const step = 300 / (values.length - 1);
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(40 - ((v - min) / range) * 36).toFixed(1)}`).join(' ');
  svg.innerHTML = `<polyline points="${points}" fill="none" stroke="#45c8ff" stroke-width="2" />`;
}

async function refreshWallboard(){
  try {
    const data = await fetch('/api/mission-control').then(r => r.json());
    const p = data.proxmox || {};
    const w = data.wazuh || {};
    const v = w.vulnerabilities || {};
    const h = w.health || {};
    const n = data.network || {};
    const a = data.assessment || {};

    const state = document.getElementById('wall-state');
    if (p.ok && p.quorum) { state.textContent = 'OPERATIONAL'; state.className = 'mission-green'; }
    else if (p.ok) { state.textContent = 'DEGRADED'; state.className = 'mission-yellow'; }
    else { state.textContent = 'API ERROR'; state.className = 'mission-red'; }

    const badge = document.getElementById('wall-incident-badge');
    badge.classList.toggle('active', !!data.incident_mode);
    badge.textContent = data.incident_mode ? `INCIDENT MODE - ${(data.active_scenario || {}).name || ''}` : 'INCIDENT MODE';

    const signals = [p.ok && p.quorum, w.ok, n.internet, n.dns].filter(x => x !== undefined);
    const healthPct = signals.length ? Math.round((signals.filter(Boolean).length / signals.length) * 100) : 0;
    document.getElementById('wall-health-pct').textContent = healthPct + '%';
    document.getElementById('wall-health-bar').style.width = healthPct + '%';
    document.getElementById('wall-health-detail').textContent =
      `Health ${healthPct}% • Wazuh ${w.ok ? 'LIVE' : 'DEGRADED'} • ${h.active_agents || 0}/${h.total_agents || 0} agents • ${v.total || 0} vulns`;

    document.getElementById('wall-quorum').textContent = p.quorum ? 'QUORATE' : 'NO QUORUM';
    document.getElementById('wall-quorum-sub').textContent = `${p.online_nodes || 0} nodes online`;
    document.getElementById('wall-qmodel').textContent = (p.qdevice_name || p.quorum_model || '-').toUpperCase();
    document.getElementById('wall-vms').textContent = `${p.running_vms || 0} / ${(p.vms || []).length}`;
    document.getElementById('wall-threat').textContent = w.threat_level || 'UNKNOWN';
    document.getElementById('wall-agents-sub').textContent = `${h.active_agents || 0}/${h.total_agents || 0} agents`;
    document.getElementById('wall-vulns').textContent = v.total || 0;
    document.getElementById('wall-internet').textContent = n.internet ? 'ONLINE' : 'CHECK';

    document.getElementById('wall-crit').textContent = v.critical || 0;
    document.getElementById('wall-high').textContent = v.high || 0;
    document.getElementById('wall-med').textContent = v.medium || 0;
    document.getElementById('wall-low').textContent = v.low || 0;

    document.getElementById('assess-infra').textContent = a.infrastructure || '-';
    document.getElementById('assess-soc').textContent = a.soc || '-';
    document.getElementById('assess-hunting').textContent = a.threat_hunting || '-';
    document.getElementById('assess-action').textContent = a.recommended_action || '-';

    const nodesEl = document.getElementById('wall-nodes');
    nodesEl.innerHTML = '';
    (p.nodes || []).forEach(node => {
      const cpu = (node.cpu || 0) * 100;
      const ram = node.maxmem ? (node.mem / node.maxmem) * 100 : 0;
      const disk = node.maxdisk ? (node.disk / node.maxdisk) * 100 : 0;
      nodesEl.innerHTML += `<article class="device-card wall-node-card hover-card" data-href="/cluster">
        <h3><span class="pulse-dot" style="background:${node.status === 'online' ? 'var(--green)' : 'var(--red)'};box-shadow:0 0 10px ${node.status === 'online' ? 'var(--green)' : 'var(--red)'};"></span>${node.node}</h3>
        <div class="mini-gauge-row">${gaugeHTML('CPU', cpu)}${gaugeHTML('RAM', ram)}${gaugeHTML('DISK', disk)}</div>
        <div class="mono" style="font-size:11px;">Uptime ${uptime(node.uptime)}</div>
      </article>`;
    });

    const hunting = w.threat_hunting || {};
    const alerts = hunting.recent_alerts || [];
    document.getElementById('wall-alerts').textContent = alerts.length;
    document.getElementById('wall-top-rule').textContent = alerts.length ? (alerts[0].rule || '-') : '-';
    document.getElementById('wall-alert-status').textContent = alerts.length ? `${alerts.length} alert record(s) sampled` : 'No recent alert docs — alert index returned no sampled alerts.';

    sparkline('wall-vuln-sparkline', data.vuln_trend || []);
    sparkline('wall-agent-sparkline', data.agent_trend || []);
  } catch (e) {
    console.log('Wallboard refresh failed', e);
  }
}
refreshWallboard();
setInterval(refreshWallboard, 5000);
