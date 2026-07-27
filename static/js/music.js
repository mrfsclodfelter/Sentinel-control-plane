let libraryTracks = [];
let openEditors = new Set();
let sortField = 'name';
let sortDir = 1;
let searchQuery = '';

function formatDuration(seconds){
  if (!seconds && seconds !== 0) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function thumbHTML(t){
  if (t.has_artwork) {
    return `<img class="music-thumb" src="/api/music/artwork/${encodeURIComponent(t.file)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'music-thumb-placeholder',textContent:'♫'}))">`;
  }
  return `<div class="music-thumb-placeholder">&#9834;</div>`;
}

function visibleTracks(){
  let tracks = libraryTracks;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    tracks = tracks.filter(t =>
      (t.name || '').toLowerCase().includes(q) ||
      (t.artist || '').toLowerCase().includes(q) ||
      (t.album || '').toLowerCase().includes(q));
  }
  return [...tracks].sort((a, b) => {
    const av = a[sortField], bv = b[sortField];
    if (sortField === 'duration') return ((av || 0) - (bv || 0)) * sortDir;
    return String(av || '').localeCompare(String(bv || '')) * sortDir;
  });
}

function renderLibraryTable(){
  const body = document.getElementById('music-library-body');
  const empty = document.getElementById('music-library-empty');
  const rows = visibleTracks();
  body.innerHTML = rows.map(t => `
    <tr data-file="${t.file}">
      <td>${thumbHTML(t)}</td>
      <td>${t.name}</td>
      <td class="muted">${t.artist || '-'}</td>
      <td class="muted">${t.album || '-'}</td>
      <td class="mono">${formatDuration(t.duration)}</td>
      <td class="music-lib-actions">
        <button type="button" class="small-button" data-play="${t.file}">Play</button>
        <button type="button" class="small-button danger-soft" data-delete="${t.file}">Delete</button>
      </td>
    </tr>`).join('');
  empty.style.display = libraryTracks.length ? 'none' : 'block';
  if (libraryTracks.length && !rows.length) {
    empty.style.display = 'block';
    empty.textContent = 'No tracks match your search.';
  } else {
    empty.textContent = 'No tracks uploaded yet.';
  }

  document.querySelectorAll('.music-lib-table th[data-sort]').forEach(th => {
    th.classList.toggle('sort-active', th.dataset.sort === sortField);
    th.textContent = th.textContent.replace(/ [▲▼]$/, '') + (th.dataset.sort === sortField ? (sortDir === 1 ? ' ▲' : ' ▼') : '');
  });
}

document.querySelectorAll('.music-lib-table th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const field = th.dataset.sort;
    if (sortField === field) sortDir *= -1;
    else { sortField = field; sortDir = 1; }
    renderLibraryTable();
  });
});

document.getElementById('music-search').addEventListener('input', (e) => {
  searchQuery = e.target.value.trim();
  renderLibraryTable();
});

async function loadLibrary(){
  const res = await fetch('/api/music/tracks');
  const data = await res.json();
  libraryTracks = data.tracks || [];
  renderLibraryTable();
  renderPlaylists();
}
loadLibrary();

document.getElementById('music-library-body').addEventListener('click', async (e) => {
  const play = e.target.closest('[data-play]');
  const del = e.target.closest('[data-delete]');
  if (play) {
    await fetch('/api/music/control', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: 'play', file: play.dataset.play})});
  }
  if (del) {
    if (!confirm('Delete this track?')) return;
    await fetch('/api/music/delete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({file: del.dataset.delete})});
    loadLibrary();
  }
});

async function uploadFiles(fileList){
  if (!fileList || !fileList.length) return;
  const fd = new FormData();
  for (const f of fileList) fd.append('files', f);
  const res = await fetch('/api/music/upload', {method: 'POST', body: fd});
  const data = await res.json();
  if (data.rejected && data.rejected.length) alert('Some files were rejected: ' + data.rejected.map(r => r.file).join(', '));
  loadLibrary();
}

const dropZone = document.getElementById('music-drop-zone');
const uploadInput = document.getElementById('music-upload-input');

document.getElementById('music-upload-browse').addEventListener('click', () => uploadInput.click());
uploadInput.addEventListener('change', () => {
  uploadFiles(uploadInput.files);
  uploadInput.value = '';
});

['dragenter', 'dragover'].forEach(evt => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.style.borderColor = 'var(--blue)';
    dropZone.style.background = 'rgba(69,200,255,.06)';
  });
});
['dragleave', 'drop'].forEach(evt => {
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.style.borderColor = 'rgba(69,200,255,.3)';
    dropZone.style.background = 'transparent';
  });
});
dropZone.addEventListener('drop', (e) => {
  uploadFiles(e.dataTransfer.files);
});

// ---------------------------------------------------------------------
// Playlists
// ---------------------------------------------------------------------

let playlists = [];

async function loadPlaylists(){
  const res = await fetch('/api/playlists');
  const data = await res.json();
  playlists = data.playlists || [];
  renderPlaylists();
}

function trackOptionsHTML(excludeFiles){
  return libraryTracks
    .filter(t => !excludeFiles.includes(t.file))
    .map(t => `<option value="${t.file}">${t.name}${t.artist ? ' - ' + t.artist : ''}</option>`)
    .join('');
}

function renderPlaylists(){
  const grid = document.getElementById('playlist-grid');
  if (!playlists.length) {
    grid.innerHTML = '<div class="alert warn">No playlists yet - create one above.</div>';
    return;
  }
  grid.innerHTML = playlists.map(p => {
    const editorOpen = openEditors.has(p.id);
    const trackRows = p.tracks.map((t, i) => `
      <li class="playlist-track-row" draggable="true" data-file="${t.file}" data-index="${i}">
        <span class="drag-handle">&#10495;</span>
        ${thumbHTML(t)}
        <span class="pt-name">${t.name}</span>
        <span class="pt-artist">${t.artist || ''}</span>
        <button type="button" class="tiny-remove" data-remove-track="${t.file}" title="Remove">&times;</button>
      </li>`).join('');
    return `
    <article class="device-card hover-card" data-playlist-id="${p.id}">
      <div class="device-top"><h3>${p.name}</h3><span class="muted">${p.track_count} track${p.track_count === 1 ? '' : 's'}</span></div>
      <div class="vm-action-row">
        <button type="button" class="small-button" data-play-playlist="${p.id}">Play</button>
        <button type="button" class="small-button" data-edit-playlist="${p.id}">${editorOpen ? 'Close' : 'Edit'}</button>
        <button type="button" class="small-button danger-soft" data-delete-playlist="${p.id}">Delete</button>
      </div>
      <div class="playlist-editor" data-playlist-editor="${p.id}" style="display:${editorOpen ? 'block' : 'none'};">
        <ul class="playlist-track-list" data-playlist-list="${p.id}">${trackRows || '<li class="muted" style="padding:6px 0;">No tracks yet.</li>'}</ul>
        <select class="cerb-input" data-add-track="${p.id}">
          <option value="">+ Add track...</option>
          ${trackOptionsHTML(p.tracks.map(t => t.file))}
        </select>
      </div>
    </article>`;
  }).join('');
  wireDragAndDrop();
}

document.getElementById('playlist-new-btn').addEventListener('click', async () => {
  const input = document.getElementById('playlist-name-input');
  const name = input.value.trim();
  if (!name) return;
  const res = await fetch('/api/playlists/manage', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name})});
  const data = await res.json();
  if (!data.ok) { alert(data.error || 'Could not create playlist'); return; }
  input.value = '';
  loadPlaylists();
});

async function savePlaylistOrder(playlistId){
  const list = document.querySelector(`[data-playlist-list="${playlistId}"]`);
  const files = Array.from(list.querySelectorAll('[data-file]')).map(li => li.dataset.file);
  await fetch(`/api/playlists/manage/${playlistId}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tracks: files}),
  });
}

document.getElementById('playlist-grid').addEventListener('click', async (e) => {
  const play = e.target.closest('[data-play-playlist]');
  const edit = e.target.closest('[data-edit-playlist]');
  const del = e.target.closest('[data-delete-playlist]');
  const removeTrack = e.target.closest('[data-remove-track]');

  if (play) {
    const res = await fetch(`/api/playlists/manage/${play.dataset.playPlaylist}/play`, {method: 'POST'});
    const data = await res.json();
    if (!data.ok) alert(data.error || 'Could not play playlist');
  }
  if (edit) {
    const id = edit.dataset.editPlaylist;
    if (openEditors.has(id)) openEditors.delete(id); else openEditors.add(id);
    renderPlaylists();
  }
  if (del) {
    if (!confirm('Delete this playlist? Tracks stay in your library.')) return;
    await fetch(`/api/playlists/manage/${del.dataset.deletePlaylist}`, {method: 'DELETE'});
    openEditors.delete(del.dataset.deletePlaylist);
    loadPlaylists();
  }
  if (removeTrack) {
    const article = removeTrack.closest('[data-playlist-id]');
    const playlistId = article.dataset.playlistId;
    const li = removeTrack.closest('[data-file]');
    li.remove();
    await savePlaylistOrder(playlistId);
    loadPlaylists();
  }
});

document.getElementById('playlist-grid').addEventListener('change', async (e) => {
  const select = e.target.closest('[data-add-track]');
  if (!select || !select.value) return;
  const playlistId = select.dataset.addTrack;
  const list = document.querySelector(`[data-playlist-list="${playlistId}"]`);
  const currentFiles = Array.from(list.querySelectorAll('[data-file]')).map(li => li.dataset.file);
  currentFiles.push(select.value);
  await fetch(`/api/playlists/manage/${playlistId}`, {
    method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tracks: currentFiles}),
  });
  loadPlaylists();
});

function wireDragAndDrop(){
  document.querySelectorAll('.playlist-track-list').forEach(list => {
    const playlistId = list.dataset.playlistList;
    list.querySelectorAll('.playlist-track-row').forEach(row => {
      row.addEventListener('dragstart', () => row.classList.add('dragging'));
      row.addEventListener('dragend', () => {
        row.classList.remove('dragging');
        savePlaylistOrder(playlistId);
      });
    });
    list.addEventListener('dragover', (e) => {
      e.preventDefault();
      const dragging = list.querySelector('.dragging');
      if (!dragging) return;
      const after = Array.from(list.querySelectorAll('.playlist-track-row:not(.dragging)')).find(row => {
        const box = row.getBoundingClientRect();
        return e.clientY < box.top + box.height / 2;
      });
      if (after) list.insertBefore(dragging, after);
      else list.appendChild(dragging);
    });
  });
}

loadPlaylists();
