function fmtPct(value){ return (!value ? "0.0" : (value * 100).toFixed(1)) + "%"; }
function fmtGB(bytes){ return (!bytes ? "0.0" : (bytes / 1073741824).toFixed(1)) + "GB"; }
async function refreshGlobalTicker(){ const el=document.getElementById("global-ticker-content"); if(!el)return; try{ const data=await fetch('/api/summary').then(r=>r.json()); const p=data.proxmox||{}, b=data.backup||{}, n=data.network||{}, w=data.wazuh||{}, v=w.vulnerabilities||{}; const nodeParts=(p.nodes||[]).map(node=>`${node.node.toUpperCase()} CPU ${fmtPct(node.cpu)} RAM ${fmtGB(node.mem)}/${fmtGB(node.maxmem)}`); const runningVMs=(p.vms||[]).filter(vm=>vm.status==='running').map(vm=>vm.name||('VM'+vm.vmid)).slice(0,8); const sec=`WAZUH ${w.health&&w.health.ok?'LIVE':'DEGRADED'} THREAT ${w.threat_level||'UNKNOWN'} VULNS ${v.total||0} CRIT ${v.critical||0} HIGH ${v.high||0} AGENTS ${w.health?w.health.active_agents:0}/${w.health?w.health.total_agents:0}`; const text=["SENTINEL LIVE",sec,`QUORUM ${p.quorum?'OK':'CHECK'}`,`QDEVICE ${p.qdevice?(p.qdevice_name||'OSIRIS WITNESS'):'UNKNOWN'}`,`VMS ${p.running_vms||0}/${(p.vms||[]).length} RUNNING`,runningVMs.length?`ACTIVE VMS: ${runningVMs.join(", ")}`:"ACTIVE VMS: NONE",`BACKUP JOBS ${(b.jobs||[]).length}`,`INTERNET ${n.internet?'ONLINE':'CHECK'}`,`DNS ${n.dns?'OK':'CHECK'}`,...nodeParts].join("  •  ")+"  •  "; el.textContent=text+text; }catch(e){el.textContent="SENTINEL LIVE • TELEMETRY REFRESH FAILED • CHECK SERVICE LOGS • ";} }
refreshGlobalTicker(); setInterval(refreshGlobalTicker,5000);

// seamless ticker v8.1
document.addEventListener('DOMContentLoaded', ()=>{
  document.querySelectorAll('.global-ticker,.ticker,.data-ticker').forEach(ticker=>{
    const inner = ticker.firstElementChild || ticker;
    if(inner && !inner.dataset.seamlessDuplicated){
      inner.dataset.seamlessDuplicated = 'true';
      inner.innerHTML = inner.innerHTML + ' &nbsp; • &nbsp; ' + inner.innerHTML;
    }
  });
});

// v8.2 seamless ticker helper
document.addEventListener('DOMContentLoaded', ()=>{
  document.querySelectorAll('.global-ticker,.ticker,.data-ticker').forEach(ticker=>{
    const content = ticker.firstElementChild || ticker;
    if(content && !content.dataset.looped){
      content.dataset.looped = "true";
      content.innerHTML = content.innerHTML + ' &nbsp; • &nbsp; ' + content.innerHTML;
    }
  });
});
