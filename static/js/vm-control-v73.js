window.CERBERUS_VM_CONTROL_VERSION = "7.3.0";

function vmPayload(btn){
  const card = btn.closest('.vm-operation-card');
  return {
    kind: btn.dataset.kind || '',
    action: btn.dataset.action || '',
    node: btn.dataset.node || (card ? card.dataset.node : ''),
    vmid: btn.dataset.vmid || (card ? card.dataset.vmid : ''),
    name: btn.dataset.name || (card ? card.dataset.name : '')
  };
}

async function postJSON(url, payload){
  const res = await fetch(url, {
    method:'POST',
    headers:{'Content-Type':'application/json', 'Accept':'application/json'},
    body:JSON.stringify(payload)
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); }
  catch(e){ throw new Error(`Non-JSON response: ${text.slice(0,180)}`); }
  if(!res.ok || !data.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

async function handleVmButton(btn){
  const p = vmPayload(btn);
  if(!p.node || !p.vmid){
    alert(`Cerberus Ops v7.3 blocked empty payload before submit. node=${p.node || '[missing]'} vmid=${p.vmid || '[missing]'}`);
    return;
  }

  if(p.kind === 'action'){
    if(!confirm(`Submit ${p.action} for ${p.name}?`)) return;
    await postJSON('/api/vm/action', {node:p.node, vmid:p.vmid, name:p.name, action:p.action});
    alert(`${p.action} submitted for ${p.name}.`);
    return;
  }

  if(p.kind === 'backup'){
    if(!confirm(`Submit backup for ${p.name}?`)) return;
    await postJSON('/api/vm/backup', {node:p.node, vmid:p.vmid, name:p.name});
    alert(`Backup submitted for ${p.name}.`);
    return;
  }

  if(p.kind === 'snapshot'){
    if(!confirm(`Create snapshot for ${p.name}?`)) return;
    await postJSON('/api/vm/snapshot', {node:p.node, vmid:p.vmid, name:p.name});
    alert(`Snapshot submitted for ${p.name}.`);
    return;
  }

  if(p.kind === 'console'){
    const data = await postJSON('/api/vm/console', {node:p.node, vmid:p.vmid, name:p.name});
    if(data.url){
      window.open(data.url, '_blank', 'noopener,noreferrer');
    } else {
      alert('Console route responded but did not include a URL.');
    }
    return;
  }

  if(p.kind === 'monitor'){
    const command = prompt('QEMU monitor command:', 'info status');
    if(!command) return;
    const data = await postJSON('/api/vm/monitor', {node:p.node, vmid:p.vmid, name:p.name, command});
    alert(JSON.stringify(data.result, null, 2).slice(0, 1800));
    return;
  }

  if(p.kind === 'migrate'){
    const target = prompt(`Target node for ${p.name}:`, '');
    if(!target) return;
    if(!confirm(`Migrate ${p.name} from ${p.node} to ${target}?`)) return;
    await postJSON('/api/vm/migrate', {node:p.node, vmid:p.vmid, name:p.name, target, online:true});
    alert(`Migration submitted for ${p.name}.`);
    return;
  }

  if(p.kind === 'clone'){
    const newid = prompt(`New VMID for clone of ${p.name}:`, '');
    if(!newid) return;
    const cloneName = prompt('Clone name:', `${p.name}-clone`);
    if(!confirm(`Clone ${p.name} to VMID ${newid}?`)) return;
    await postJSON('/api/vm/clone', {node:p.node, vmid:p.vmid, name:p.name, newid, clone_name:cloneName, full:true});
    alert(`Clone submitted for ${p.name}.`);
    return;
  }
}

document.addEventListener('click', async (e)=>{
  const btn = e.target.closest('.vm-op-btn');
  const backupAll = e.target.closest('#backup-all-btn');
  if(!btn && !backupAll) return;

  e.preventDefault();
  e.stopPropagation();

  try{
    if(backupAll){
      if(!confirm('Submit backup for all visible VMs?')) return;
      await postJSON('/api/vm/backup-all', {});
      alert('Backup-all submitted. Check Operations Queue.');
      return;
    }
    await handleVmButton(btn);
  }catch(err){
    alert(err.message);
  }
}, true);
