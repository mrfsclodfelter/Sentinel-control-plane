(function(){
  const btn = document.getElementById('mini-player-listen');
  const statusEl = document.getElementById('mini-player-listen-status');
  const responseAudio = document.getElementById('mini-player-listen-audio');
  if (!btn) return;

  // Click-to-record-fixed-duration, not press-and-hold, and captured with
  // the raw Web Audio API (AudioContext + ScriptProcessorNode) rather than
  // MediaRecorder. This isn't a style choice - v1's push-to-talk used
  // exactly this approach and worked reliably on the same phone that kept
  // hitting a WebKit bug with MediaRecorder.onstop never firing in v2's
  // press-and-hold version. Fixed duration also sidesteps the whole class
  // of press/release race conditions (permission prompt mid-hold, stuck
  // "listening" state, etc.) since there's no release to race against.
  const RECORD_MS = 4500;
  let busy = false;

  const SILENT_WAV = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
  let audioUnlocked = false;
  function unlockAudioPlayback(){
    if (audioUnlocked) return;
    audioUnlocked = true;
    [responseAudio, document.getElementById('mini-player-audio')].forEach((el) => {
      if (!el) return;
      const hadSrc = el.src;
      el.src = SILENT_WAV;
      const p = el.play();
      if (p && p.then) {
        p.then(() => {
          el.pause();
          if (hadSrc) el.src = hadSrc; else el.removeAttribute('src');
        }).catch(() => {});
      }
    });
  }
  window.sentinelUnlockAudio = unlockAudioPlayback;

  function setStatus(text){ if (statusEl) statusEl.textContent = text || ''; }

  function setState(next){
    btn.classList.remove('listening', 'processing', 'speaking');
    if (next === 'listening') { btn.classList.add('listening'); btn.textContent = '🎙 Listening…'; }
    else if (next === 'processing') { btn.classList.add('processing'); btn.textContent = '… Talk'; }
    else { btn.textContent = '🎙 Talk'; }
  }

  function flattenFloat32(chunks){
    let length = 0;
    chunks.forEach(c => length += c.length);
    const result = new Float32Array(length);
    let offset = 0;
    chunks.forEach(c => { result.set(c, offset); offset += c.length; });
    return result;
  }

  function encodeWav(samples, sampleRate){
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    function writeString(offset, value){ for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); }
    writeString(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); writeString(8, 'WAVE');
    writeString(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    writeString(36, 'data'); view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const sample = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return new Blob([view], { type: 'audio/wav' });
  }

  async function recordWav(durationMs){
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass();
    if (audioContext.state === 'suspended') await audioContext.resume();

    const source = audioContext.createMediaStreamSource(stream);
    // createScriptProcessor is deprecated in favor of AudioWorklet, but it
    // needs no separate worklet module file and has the longest, most
    // consistent cross-browser track record - exactly what's wanted here
    // after MediaRecorder's inconsistency on this exact device.
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const chunks = [];

    processor.onaudioprocess = (event) => {
      chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      event.outputBuffer.getChannelData(0).fill(0);
    };

    source.connect(processor);
    processor.connect(audioContext.destination);

    await new Promise((resolve) => setTimeout(resolve, durationMs));

    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    await audioContext.close();

    return encodeWav(flattenFloat32(chunks), audioContext.sampleRate);
  }

  async function handleTalk(){
    if (busy) return;

    if (!window.isSecureContext || !navigator.mediaDevices) {
      const httpsUrl = `https://${location.hostname}:8443${location.pathname}`;
      setStatus(`Mic needs HTTPS - use ${httpsUrl}`);
      alert(`The microphone only works on the secure link. Open this instead:\n\n${httpsUrl}`);
      return;
    }

    unlockAudioPlayback();
    busy = true;
    setState('listening');
    setStatus(`Listening… (${(RECORD_MS / 1000).toFixed(1)}s)`);

    let wavBlob;
    try {
      wavBlob = await recordWav(RECORD_MS);
    } catch (e) {
      busy = false;
      setState('idle');
      const name = e && e.name ? e.name : 'unknown';
      const msg = name === 'NotAllowedError'
        ? 'Microphone permission denied. On iPhone: Settings app -> Chrome -> Microphone must be ON (this is separate from any in-page prompt).'
        : `Mic error (${name}): ${e && e.message ? e.message : e}`;
      setStatus(msg);
      // The whole failure happens before any network request, in well
      // under a second - the button's red "listening" flash is easy to
      // read as "something happened" when actually nothing was sent yet.
      // An alert forces enough time to actually read why.
      alert(msg);
      return;
    }

    setState('processing');
    setStatus(`Transcribing… (${wavBlob.size} bytes recorded)`);

    const form = new FormData();
    form.append('audio', wavBlob, 'command.wav');

    const controller = new AbortController();
    const networkTimeout = setTimeout(() => controller.abort(), 15000);

    try {
      const res = await fetch('/api/voice/command-audio-browser', { method: 'POST', body: form, signal: controller.signal });
      const data = await res.json();
      handleResult(data);
    } catch (e) {
      setState('idle');
      setStatus(e && e.name === 'AbortError' ? 'Request timed out - check your connection' : `Request failed: ${e && e.message ? e.message : e}`);
    } finally {
      clearTimeout(networkTimeout);
      busy = false;
    }
  }

  function handleResult(data){
    const heard = data.display_phrase || data.phrase || '';
    const automation = data.automation || {};

    if (!data.ok) {
      setState('idle');
      setStatus(heard ? `Didn't catch a command in: "${heard}"` : (automation.error || 'No speech detected'));
      return;
    }

    let name = 'Command';
    if (automation.builtin === 'play' && automation.playlist) name = `Playing ${automation.playlist} playlist`;
    else if (automation.builtin === 'play') name = `Playing ${automation.track}`;
    else if (automation.builtin === 'stop') name = 'Stopping music';
    else if ((automation.automation || {}).name) name = automation.automation.name;
    setStatus(`Heard "${heard}" → ${name}`);

    if (data.audio_base64 && responseAudio) {
      responseAudio.volume = window.__sentinelVoiceVolume != null ? window.__sentinelVoiceVolume : 1;
      const bytes = atob(data.audio_base64);
      const buf = new Uint8Array(bytes.length);
      for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
      responseAudio.src = url;
      btn.classList.remove('processing');
      btn.classList.add('speaking');
      responseAudio.onended = () => {
        btn.classList.remove('speaking');
        URL.revokeObjectURL(url);
        setState('idle');
      };
      responseAudio.play().catch((e) => {
        btn.classList.remove('speaking');
        setState('idle');
        setStatus(`Heard "${heard}" → ${name} (playback blocked: ${e && e.name ? e.name : 'unknown'})`);
      });
    } else {
      setState('idle');
    }
  }

  btn.addEventListener('click', handleTalk);

  fetch('/api/audio-settings').then(r => r.json()).then(data => {
    if (data.ok) window.__sentinelVoiceVolume = data.settings.voice_volume / 100;
  }).catch(() => {});
})();
