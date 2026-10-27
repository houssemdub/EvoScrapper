// Watch-Together (P8) Transport & State Sync over CometNet
let myPartyPeerId = 'peer_' + Math.random().toString(36).substring(2, 10);
let activePartyCode = null;
let lastPartySequence = 0;
let isApplyingPartyEvent = false;

function toggleWatchPartyPanel() {
  const popover = document.getElementById('watch-party-popover');
  if (popover) popover.classList.toggle('hidden');
}

async function createWatchParty() {
  const active = (window.state && window.state.discover) ? window.state.discover.activeStream : null;
  const statusEl = document.getElementById('watch-party-status');
  if (!active || !active.infoHash) {
    if (statusEl) statusEl.innerText = 'Start playing a stream first to create a party.';
    return;
  }
  if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating room...';

  try {
    const res = await fetch('/api/v1/cometnet/party/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ info_hash: active.infoHash, host_peer_id: myPartyPeerId }),
    });
    if (!res.ok) throw new Error('Create room failed');
    const data = await res.json();
    activePartyCode = data.code.toUpperCase();
    lastPartySequence = 0;
    if (statusEl) statusEl.innerHTML = `<span style="color:#10b981;">Party code: <b>${activePartyCode}</b> (Share with friends)</span>`;
    startWatchPartyPolling();
  } catch (err) {
    if (statusEl) statusEl.innerText = `Error: ${err.message}`;
  }
}

async function joinWatchParty() {
  const input = document.getElementById('watch-party-code-input');
  const statusEl = document.getElementById('watch-party-status');
  const code = (input ? input.value : '').trim().toUpperCase();
  if (!code) return;

  if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Joining room...';

  try {
    const res = await fetch(`/api/v1/cometnet/party/${encodeURIComponent(code)}/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: myPartyPeerId }),
    });
    if (!res.ok) throw new Error('Room not found or expired');
    const data = await res.json();
    activePartyCode = code;
    lastPartySequence = 0;
    if (statusEl) statusEl.innerHTML = `<span style="color:#10b981;">Connected to party <b>${activePartyCode}</b>!</span>`;
    startWatchPartyPolling();
  } catch (err) {
    if (statusEl) statusEl.innerText = `Error: ${err.message}`;
  }
}

function startWatchPartyPolling() {
  if (window._partyPollTimer) clearInterval(window._partyPollTimer);
  window._partyPollTimer = setInterval(async () => {
    if (!activePartyCode) return;
    try {
      const res = await fetch(`/api/v1/cometnet/party/${encodeURIComponent(activePartyCode)}/events?since=${lastPartySequence}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data && Array.isArray(data.events)) {
        for (const evt of data.events) {
          if (evt.sequence > lastPartySequence) {
            lastPartySequence = evt.sequence;
            if (evt.peer_id !== myPartyPeerId) {
              applyWatchPartyEvent(evt);
            }
          }
        }
      }
    } catch (_) {}
  }, 2000);
}

function applyWatchPartyEvent(evt) {
  const video = document.getElementById('evo-video-player');
  if (!video) return;
  isApplyingPartyEvent = true;

  if (evt.action === 'seek' && Math.abs(video.currentTime - evt.position) > 1.5) {
    video.currentTime = evt.position;
  } else if (evt.action === 'play') {
    if (Math.abs(video.currentTime - evt.position) > 1.5) video.currentTime = evt.position;
    video.play().catch(() => {});
  } else if (evt.action === 'pause') {
    video.pause();
    if (Math.abs(video.currentTime - evt.position) > 1.5) video.currentTime = evt.position;
  }

  setTimeout(() => { isApplyingPartyEvent = false; }, 500);
}

function reportWatchPartyEvent(action, position) {
  if (!activePartyCode || isApplyingPartyEvent) return;
  fetch(`/api/v1/cometnet/party/${encodeURIComponent(activePartyCode)}/event`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      peer_id: myPartyPeerId,
      action: action,
      position: position || 0,
    }),
  }).catch(() => {});
}
