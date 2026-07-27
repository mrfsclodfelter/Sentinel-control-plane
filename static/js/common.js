async function fetchJSON(url){ const res = await fetch(url); return await res.json(); }
function setMissionPill(text, cls){ const pill=document.getElementById("mission-pill"); if(!pill)return; pill.textContent=text; pill.className="status-pill "+cls; }
function gb(bytes){ if(!bytes)return "0.0 GB"; return (bytes/1073741824).toFixed(1)+" GB"; }
function pct(value){ if(!value)return "0.0%"; return (value*100).toFixed(1)+"%"; }
function uptime(seconds){ if(!seconds)return "0.0 hrs"; return (seconds/3600).toFixed(1)+" hrs"; }
function gaugeHTML(label, percent){
  const p=Math.max(0,Math.min(100,percent||0));
  const status=p>=85?'danger':p>=65?'warn':'ok';
  return `<div class="gauge-wrap gauge-${status}"><div class="gauge-ring" style="--p:${p}"><div class="gauge-inner"><strong>${p.toFixed(0)}%</strong><span>${label}</span></div></div></div>`;
}

async function refreshMissionPill(){ try{ const data=await fetchJSON("/api/health"); if(data.ok&&data.quorum){setMissionPill("MISSION GREEN","online")} else if(data.ok){setMissionPill("DEGRADED","warn")} else{setMissionPill("API ERROR","offline")} }catch(e){setMissionPill("SYNC LOST","offline")} }
refreshMissionPill(); setInterval(refreshMissionPill,5000);
