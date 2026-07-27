let lastMusicCommandId = 0;
let currentAfterTrack = 'stop';
let currentFile = null;

function musicAudioEl(){
  return document.getElementById('mini-player-audio');
}

async function pollMusicCommand(){
  try {
    const res = await fetch('/api/music/command');
    const cmd = await res.json();
    if (!cmd || cmd.id === lastMusicCommandId) return;
    lastMusicCommandId = cmd.id;
    applyMusicCommand(cmd);
  } catch (e) {}
}

function applyMusicCommand(cmd){
  const audio = musicAudioEl();
  const toggle = document.getElementById('mini-player-toggle');
  const meta = document.getElementById('mini-player-meta');
  if (!audio) return;

  if (cmd.action === 'stop') {
    audio.pause();
    audio.currentTime = 0;
    if (toggle) toggle.textContent = '▶';
    if (meta) meta.textContent = 'Music standby';
    return;
  }
  if (cmd.action === 'play' && cmd.file) {
    currentAfterTrack = cmd.after_track || 'stop';
    currentFile = cmd.file;
    audio.src = `/static/music/${encodeURIComponent(cmd.file)}`;
    audio.loop = !!cmd.loop;
    audio.play().catch((e) => {
      // Most likely mobile Safari/WebKit blocking autoplay because this
      // command arrived from a background poll, not a direct tap - see
      // push-to-talk.js's unlockAudioPlayback() for the fix. Surfacing the
      // real reason here instead of swallowing it, since a silent failure
      // here previously looked identical to "nothing happened."
      if (meta) meta.textContent = `Blocked: ${e && e.name ? e.name : 'playback error'} - tap ▶ once to unlock audio`;
    });
    if (toggle) toggle.textContent = '⏸';
    if (meta) meta.textContent = cmd.file;
  }
}

async function handleTrackEnded(){
  if (currentAfterTrack === 'stop' || !currentFile) return;
  try {
    await fetch('/api/music/advance', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({after_track: currentAfterTrack, file: currentFile}),
    });
  } catch (e) {}
}

async function postMusicControl(action, extra){
  try {
    await fetch('/api/music/control', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({action}, extra || {})),
    });
  } catch (e) {}
}

async function loadMusicTrackOptions(){
  try {
    const res = await fetch('/api/music/tracks');
    const data = await res.json();
    const select = document.getElementById('mini-player-track');
    if (!select) return;
    select.innerHTML = '<option value="">Music</option>' + (data.tracks || [])
      .map(t => `<option value="${t.file}">${t.name}</option>`).join('');
  } catch (e) {}
}

async function applyMediaVolume(){
  try {
    const res = await fetch('/api/audio-settings');
    const data = await res.json();
    const audio = musicAudioEl();
    if (audio && data.ok) audio.volume = data.settings.media_volume / 100;
  } catch (e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('mini-player-toggle');
  const select = document.getElementById('mini-player-track');
  const next = document.getElementById('mini-player-next');

  applyMediaVolume();

  if (toggle) {
    toggle.addEventListener('click', () => {
      if (window.sentinelUnlockAudio) window.sentinelUnlockAudio();
      const audio = musicAudioEl();
      if (audio && !audio.paused) {
        postMusicControl('stop');
      } else if (select && select.value) {
        postMusicControl('play', {file: select.value});
      } else {
        postMusicControl('shuffle');
      }
    });
  }
  if (next) {
    next.addEventListener('click', () => postMusicControl('shuffle'));
  }

  const audio = musicAudioEl();
  if (audio) {
    audio.addEventListener('ended', handleTrackEnded);
  }

  loadMusicTrackOptions();
  pollMusicCommand();
  setInterval(pollMusicCommand, 3000);
});
