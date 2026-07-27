async function refreshListenerStatus(){
  try {
    const res = await fetch('/api/voice/listener/status');
    const data = await res.json();
    const el = document.getElementById('voice-listener-state');
    const active = data.is_active;
    el.textContent = (data.active || 'UNKNOWN').toUpperCase();
    el.className = 'led ' + (active ? 'online' : 'offline');
  } catch (e) {}
}
refreshListenerStatus();

async function controlListener(action){
  try {
    const res = await fetch(`/api/voice/listener/${action}`, {method: 'POST'});
    const data = await res.json();
    if (!data.ok) alert(data.result ? data.result.stderr || 'Action failed' : 'Action failed');
  } catch (e) { alert(e.message); }
  refreshListenerStatus();
}

document.getElementById('voice-listener-start').addEventListener('click', () => controlListener('start'));
document.getElementById('voice-listener-stop').addEventListener('click', () => controlListener('stop'));
document.getElementById('voice-listener-restart').addEventListener('click', () => controlListener('restart'));

document.getElementById('voice-say-btn').addEventListener('click', async () => {
  const text = document.getElementById('voice-say-text').value.trim();
  if (!text) return;
  try {
    const res = await fetch('/api/voice/speak', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
    const data = await res.json();
    if (!data.ok) alert(data.error || 'Speak failed - check Piper is installed and the Pi is reachable.');
  } catch (e) { alert(e.message); }
});

document.getElementById('voice-listen-btn').addEventListener('click', async () => {
  const btn = document.getElementById('voice-listen-btn');
  btn.textContent = 'Listening...';
  try {
    const res = await fetch('/api/voice/listen', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({duration: 4})});
    const data = await res.json();
    const heard = data.result && data.result.display_phrase;
    alert(heard ? `Heard: "${heard}"` : (data.error || 'No command captured.'));
  } catch (e) { alert(e.message); }
  btn.textContent = 'Listen (push to talk)';
});

const voiceSlider = document.getElementById('voice-volume-slider');
const mediaSlider = document.getElementById('media-volume-slider');
const voiceValueLabel = document.getElementById('voice-volume-value');
const mediaValueLabel = document.getElementById('media-volume-value');

async function loadAudioSettings(){
  try {
    const res = await fetch('/api/audio-settings');
    const data = await res.json();
    if (!data.ok) return;
    voiceSlider.value = data.settings.voice_volume;
    mediaSlider.value = data.settings.media_volume;
    voiceValueLabel.textContent = data.settings.voice_volume + '%';
    mediaValueLabel.textContent = data.settings.media_volume + '%';
  } catch (e) {}
}
loadAudioSettings();

async function saveAudioSettings(field, value){
  try {
    await fetch('/api/audio-settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({[field]: value}),
    });
  } catch (e) {}
}

voiceSlider.addEventListener('input', () => { voiceValueLabel.textContent = voiceSlider.value + '%'; });
mediaSlider.addEventListener('input', () => { mediaValueLabel.textContent = mediaSlider.value + '%'; });
voiceSlider.addEventListener('change', () => saveAudioSettings('voice_volume', Number(voiceSlider.value)));
mediaSlider.addEventListener('change', () => saveAudioSettings('media_volume', Number(mediaSlider.value)));
