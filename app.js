"use strict";

/* ---------------------------------------------------------------------- *
 * Config / state
 * ---------------------------------------------------------------------- */

const API_BASE_KEY = "tutanak:apiBaseUrl";
const CHUNK_MS = 6000; // record ~6s self-contained chunks, not one continuous stream
const POLL_MS = 1500;

// Default to the deployed Render backend so the published GitHub Pages site
// works out of the box; "Ayarlar" still lets you point at localhost for
// local development.
function getApiBase() {
  return localStorage.getItem(API_BASE_KEY) || "https://toplanti-tutanak-backend.onrender.com";
}
function setApiBase(url) {
  localStorage.setItem(API_BASE_KEY, url.replace(/\/$/, ""));
}

const state = {
  meetingId: null,
  editToken: null,
  agendaItems: [], // draft strings before creation; {id,title} after
  participants: [], // draft strings before creation; {id,display_name} after
  segments: [],
  lastSegmentId: 0,
  activeSpeakerId: null, // null = "Bilinmiyor"
  currentAgendaIdx: 0,
  recording: false,
  pollTimer: null,
  mediaStream: null,
  meetingMeta: null, // hydrated final GET response
  uploadQueue: [], // {blob, participantId} — drained one at a time, independent of recording
  uploading: false,
};

/* ---------------------------------------------------------------------- *
 * Edit-token storage (no user accounts — a per-meeting secret instead)
 * ---------------------------------------------------------------------- */

function tokenKey(meetingId) {
  return `tutanak:editToken:${meetingId}`;
}
function saveEditToken(meetingId, token) {
  localStorage.setItem(tokenKey(meetingId), token);
}

/* ---------------------------------------------------------------------- *
 * API client
 * ---------------------------------------------------------------------- */

async function apiFetch(path, { method = "GET", body, isForm = false, auth = true } = {}) {
  const headers = {};
  if (auth && state.editToken) headers["X-Edit-Token"] = state.editToken;
  if (body && !isForm) headers["Content-Type"] = "application/json";

  const res = await fetch(`${getApiBase()}${path}`, {
    method,
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const message = (data && data.detail) || `İstek başarısız (${res.status})`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

const api = {
  createMeeting: (payload) => apiFetch("/api/meetings", { method: "POST", body: payload, auth: false }),
  getMeeting: (id) => apiFetch(`/api/meetings/${id}`),
  startMeeting: (id) => apiFetch(`/api/meetings/${id}/start`, { method: "POST" }),
  uploadAudioChunk: (id, blob, participantId) => {
    const form = new FormData();
    form.append("audio", blob, "chunk.webm");
    if (participantId != null) form.append("participant_id", String(participantId));
    return apiFetch(`/api/meetings/${id}/audio-chunk`, { method: "POST", body: form, isForm: true });
  },
  getSegments: (id, afterId) => apiFetch(`/api/meetings/${id}/segments?after_id=${afterId}`),
  patchSegment: (id, segId, payload) =>
    apiFetch(`/api/meetings/${id}/segments/${segId}`, { method: "PATCH", body: payload }),
  endMeeting: (id) => apiFetch(`/api/meetings/${id}/end`, { method: "POST" }),
};

/* ---------------------------------------------------------------------- *
 * Screen / tab state machine
 * ---------------------------------------------------------------------- */

const steps = document.querySelectorAll(".step");
const screens = document.querySelectorAll(".screen");

// The steps row is a progress indicator only (not clickable) — each screen
// depends on state built up by the previous one (a meeting id + edit token,
// a started recording session, a final hydrated transcript), so jumping
// screens out of order isn't meaningful here.
function showScreen(id) {
  steps.forEach((s) => s.classList.toggle("active", s.dataset.target === id));
  screens.forEach((s) => s.classList.toggle("active", s.id === id));
}

/* ---------------------------------------------------------------------- *
 * Settings (API base URL) — minimal affordance for a skeleton phase
 * ---------------------------------------------------------------------- */

document.getElementById("settingsBtn").addEventListener("click", () => {
  const current = getApiBase();
  const next = prompt("Backend adresi:", current);
  if (next && next.trim()) setApiBase(next.trim());
});

document.getElementById("keyBtn").addEventListener("click", () => {
  if (state.editToken) {
    prompt("Düzenleme anahtarınız (bu tarayıcıda saklandı — farklı bir cihazda gerekirse kopyalayın):", state.editToken);
  }
});

/* ---------------------------------------------------------------------- *
 * Kurulum (setup) screen
 * ---------------------------------------------------------------------- */

const agendaListEl = document.getElementById("agendaList");
const participantListEl = document.getElementById("participantList");
const setupError = document.getElementById("setupError");

function renderAgendaList() {
  agendaListEl.innerHTML = "";
  state.agendaItems.forEach((title, i) => {
    const row = document.createElement("div");
    row.className = "list-item";
    row.innerHTML = `
      <span class="idx">${String(i + 1).padStart(2, "0")}</span>
      <span class="item-text"></span>
      <button class="remove-btn" aria-label="Kaldır">×</button>
    `;
    row.querySelector(".item-text").textContent = title;
    row.querySelector(".remove-btn").addEventListener("click", () => {
      state.agendaItems.splice(i, 1);
      renderAgendaList();
    });
    agendaListEl.appendChild(row);
  });
}

function renderParticipantList() {
  participantListEl.innerHTML = "";
  state.participants.forEach((name, i) => {
    const row = document.createElement("div");
    row.className = "list-item";
    row.innerHTML = `
      <span class="avatar"></span>
      <span class="item-text"></span>
      <button class="remove-btn" aria-label="Kaldır">×</button>
    `;
    row.querySelector(".avatar").textContent = name.slice(0, 2).toUpperCase();
    row.querySelector(".item-text").textContent = name;
    row.querySelector(".remove-btn").addEventListener("click", () => {
      state.participants.splice(i, 1);
      renderParticipantList();
    });
    participantListEl.appendChild(row);
  });
}

document.getElementById("agendaAddBtn").addEventListener("click", () => {
  const input = document.getElementById("agendaDraft");
  const v = input.value.trim();
  if (!v) return;
  state.agendaItems.push(v);
  input.value = "";
  renderAgendaList();
});
document.getElementById("agendaDraft").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("agendaAddBtn").click();
});

document.getElementById("participantAddBtn").addEventListener("click", () => {
  const input = document.getElementById("participantDraft");
  const v = input.value.trim();
  if (!v) return;
  state.participants.push(v);
  input.value = "";
  renderParticipantList();
});
document.getElementById("participantDraft").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("participantAddBtn").click();
});

document.getElementById("startBtn").addEventListener("click", async () => {
  const title = document.getElementById("titleInput").value.trim();
  setupError.hidden = true;
  if (!title) {
    setupError.textContent = "Lütfen toplantı başlığı girin.";
    setupError.hidden = false;
    return;
  }
  const btn = document.getElementById("startBtn");
  btn.disabled = true;
  btn.textContent = "Başlatılıyor…";
  try {
    const created = await api.createMeeting({
      title,
      agenda_items: state.agendaItems,
      participants: state.participants,
    });
    state.meetingId = created.id;
    state.editToken = created.edit_token;
    saveEditToken(created.id, created.edit_token);

    const started = await api.startMeeting(created.id);
    hydrateFromMeeting(started);
    document.getElementById("keyBtn").hidden = false;
    enterLiveScreen();
  } catch (err) {
    setupError.textContent = err.message || "Toplantı başlatılamadı.";
    setupError.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Toplantıyı Başlat";
  }
});

/* ---------------------------------------------------------------------- *
 * Shared: hydrate local state from a MeetingResponse
 * ---------------------------------------------------------------------- */

function hydrateFromMeeting(meeting) {
  state.meetingMeta = meeting;
  state.agendaItems = meeting.agenda_items; // now [{id, order_index, title}]
  state.participants = meeting.participants; // now [{id, order_index, display_name}]
  state.segments = meeting.segments || [];
  state.lastSegmentId = state.segments.reduce((m, s) => Math.max(m, s.id), 0);
}

function participantName(id) {
  const p = state.participants.find((p) => p.id === id);
  return p ? p.display_name : null;
}

/* ---------------------------------------------------------------------- *
 * Canlı (live) screen
 * ---------------------------------------------------------------------- */

const agendaStripEl = document.getElementById("agendaStrip");
const speakerStripEl = document.getElementById("speakerStrip");
const ledgerEl = document.getElementById("ledger");
const micError = document.getElementById("micError");

function renderAgendaStrip() {
  agendaStripEl.innerHTML = "";
  state.agendaItems.forEach((item, i) => {
    const chip = document.createElement("div");
    chip.className = "agenda-chip" + (i === state.currentAgendaIdx ? " current" : "");
    chip.textContent = `${String(i + 1).padStart(2, "0")} · ${item.title}`;
    chip.addEventListener("click", () => {
      state.currentAgendaIdx = i;
      renderAgendaStrip();
    });
    agendaStripEl.appendChild(chip);
  });
}

function renderSpeakerStrip() {
  speakerStripEl.innerHTML = "";
  const unknown = document.createElement("div");
  unknown.className = "speaker-chip" + (state.activeSpeakerId === null ? " current" : "");
  unknown.textContent = "Bilinmiyor";
  unknown.addEventListener("click", () => {
    state.activeSpeakerId = null;
    renderSpeakerStrip();
  });
  speakerStripEl.appendChild(unknown);

  state.participants.forEach((p) => {
    const chip = document.createElement("div");
    chip.className = "speaker-chip" + (state.activeSpeakerId === p.id ? " current" : "");
    chip.textContent = p.display_name;
    chip.addEventListener("click", () => {
      state.activeSpeakerId = p.id;
      renderSpeakerStrip();
    });
    speakerStripEl.appendChild(chip);
  });
}

// Full rebuild — only used once, when the live screen first mounts. After
// that, new lines are appended incrementally (appendSegment) so an in-
// progress edit on an existing line survives the next poll tick.
function renderLedger() {
  document.getElementById("ledgerEmpty").hidden = state.segments.length > 0;
  ledgerEl.querySelectorAll(".line").forEach((el) => el.remove());
  state.segments.forEach((seg) => ledgerEl.appendChild(buildLineEl(seg)));
}

function appendSegment(seg) {
  document.getElementById("ledgerEmpty").hidden = true;
  ledgerEl.appendChild(buildLineEl(seg));
}

function buildLineEl(seg) {
  const line = document.createElement("div");
  line.className = "line";
  line.dataset.segId = seg.id;
  renderLineView(line, seg);
  return line;
}

function renderLineView(line, seg) {
  line.innerHTML = "";
  const tag = document.createElement("span");
  tag.className = "speaker-tag" + (seg.participant_id ? "" : " unmatched");
  tag.textContent = seg.participant_name || participantName(seg.participant_id) || "Konuşmacı belirsiz";
  const utterance = document.createElement("div");
  utterance.className = "utterance";
  utterance.textContent = seg.text;
  line.appendChild(tag);
  line.appendChild(utterance);
  if (!seg.participant_id) {
    const flag = document.createElement("span");
    flag.className = "flag";
    flag.textContent = "İsim onayı bekliyor";
    line.appendChild(flag);
  }
  line.onclick = () => renderLineEdit(line, seg);
}

function renderLineEdit(line, seg) {
  line.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "line-edit";

  const select = document.createElement("select");
  const noneOpt = document.createElement("option");
  noneOpt.value = "";
  noneOpt.textContent = "Bilinmiyor";
  select.appendChild(noneOpt);
  state.participants.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.display_name;
    if (seg.participant_id === p.id) opt.selected = true;
    select.appendChild(opt);
  });

  const textarea = document.createElement("textarea");
  textarea.value = seg.text;

  const actions = document.createElement("div");
  actions.className = "line-edit-actions";
  const saveBtn = document.createElement("button");
  saveBtn.className = "save-btn";
  saveBtn.textContent = "Kaydet";
  const cancelBtn = document.createElement("button");
  cancelBtn.className = "cancel-btn";
  cancelBtn.textContent = "İptal";
  actions.appendChild(saveBtn);
  actions.appendChild(cancelBtn);

  wrap.appendChild(select);
  wrap.appendChild(textarea);
  wrap.appendChild(actions);
  line.appendChild(wrap);

  cancelBtn.addEventListener("click", () => renderLineView(line, seg));
  saveBtn.addEventListener("click", async () => {
    const payload = {};
    const newText = textarea.value.trim();
    if (newText !== seg.text) payload.text = newText;
    const newParticipantId = select.value === "" ? null : Number(select.value);
    if (newParticipantId !== seg.participant_id) {
      if (newParticipantId === null) payload.clear_participant = true;
      else payload.participant_id = newParticipantId;
    }
    if (Object.keys(payload).length === 0) {
      renderLineView(line, seg);
      return;
    }
    try {
      const updated = await api.patchSegment(state.meetingId, seg.id, payload);
      const idx = state.segments.findIndex((s) => s.id === updated.id);
      if (idx !== -1) state.segments[idx] = updated;
      renderLineView(line, updated);
    } catch (err) {
      alert(err.message || "Satır güncellenemedi.");
      renderLineView(line, seg);
    }
  });
}

function enterLiveScreen() {
  document.getElementById("liveTitle").textContent = state.meetingMeta.title;
  document.getElementById("asrWarning").hidden = true;
  renderAgendaStrip();
  renderSpeakerStrip();
  renderLedger();
  showScreen("s2");
  document.getElementById("recPill").hidden = false;
  startRecTimer();
  startPolling();
  startRecording();
}

/* ---------------------------------------------------------------------- *
 * Elapsed-time pill
 * ---------------------------------------------------------------------- */

let recTimerHandle = null;
function startRecTimer() {
  const startedAt = state.meetingMeta.started_at ? new Date(state.meetingMeta.started_at) : new Date();
  const el = document.getElementById("recTimer");
  const tick = () => {
    const elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));
    const mm = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
    const ss = String(elapsedSec % 60).padStart(2, "0");
    el.textContent = `${mm}:${ss}`;
  };
  tick();
  recTimerHandle = setInterval(tick, 1000);
}
function stopRecTimer() {
  if (recTimerHandle) clearInterval(recTimerHandle);
  recTimerHandle = null;
  document.getElementById("recPill").hidden = true;
}

/* ---------------------------------------------------------------------- *
 * Polling for new transcript lines
 * ---------------------------------------------------------------------- */

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const fresh = await api.getSegments(state.meetingId, state.lastSegmentId);
      if (fresh.length === 0) return;
      state.lastSegmentId = Math.max(state.lastSegmentId, ...fresh.map((s) => s.id));
      fresh.forEach((seg) => {
        if (!state.segments.some((s) => s.id === seg.id)) {
          state.segments.push(seg);
          appendSegment(seg);
        }
      });
    } catch {
      /* transient network hiccup — next poll retries */
    }
  }, POLL_MS);
}
function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

/* ---------------------------------------------------------------------- *
 * Microphone capture: ~6s self-contained chunks, back to back
 * ---------------------------------------------------------------------- */

const RECORDER_MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return "";
  return RECORDER_MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function recordOneChunk(stream) {
  return new Promise((resolve, reject) => {
    let recorder;
    try {
      const mimeType = pickMimeType();
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    } catch (err) {
      reject(err);
      return;
    }
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType }));
    recorder.onerror = (e) => reject(e.error || new Error("Kayıt hatası"));
    recorder.start();
    setTimeout(() => {
      if (recorder.state !== "inactive") recorder.stop();
    }, CHUNK_MS);
  });
}

// Recording and uploading are intentionally decoupled: on a slow/CPU-
// constrained backend a single chunk's transcription can take much longer
// than the ~6s it took to record it. If recording waited for each upload to
// finish before starting the next chunk, most of the meeting would simply
// never be captured. So recording runs back-to-back on its own clock, and
// finished chunks are queued and uploaded one at a time in the background
// (one at a time, not all at once, so a slow host isn't hit with a pile of
// concurrent transcription requests on top of the one it's already behind on).
async function recordingLoop(stream) {
  while (state.recording) {
    let blob;
    try {
      blob = await recordOneChunk(stream);
    } catch (err) {
      console.error("recording a chunk failed, stopping the loop:", err);
      break;
    }
    console.log(`recorded chunk: ${blob.size} bytes, type=${blob.type}`);
    if (!state.recording) break;
    state.uploadQueue.push({ blob, participantId: state.activeSpeakerId });
    processUploadQueue();
  }
}

async function processUploadQueue() {
  if (state.uploading) return;
  const next = state.uploadQueue.shift();
  if (!next) return;
  state.uploading = true;
  try {
    const seg = await api.uploadAudioChunk(state.meetingId, next.blob, next.participantId);
    console.log("audio-chunk response:", seg);
    if (seg && !state.segments.some((s) => s.id === seg.id)) {
      state.segments.push(seg);
      state.lastSegmentId = Math.max(state.lastSegmentId, seg.id);
      appendSegment(seg);
    }
    hideAsrWarning();
  } catch (err) {
    // One bad/slow chunk shouldn't stop the meeting — keep recording — but
    // make the failure visible instead of silently dropping every line, so
    // a persistent ASR problem (e.g. the model struggling on a constrained
    // host) is obvious rather than looking like "nothing is being heard".
    console.error("audio-chunk upload failed:", err);
    showAsrWarning(err.message || "Ses tanıma isteği başarısız oldu.");
  } finally {
    state.uploading = false;
    processUploadQueue(); // drain the rest of the queue, if any piled up
  }
}

// Used when ending the meeting: wait for any chunks still queued/in-flight
// to finish uploading before calling the end endpoint (which 409s once the
// meeting is no longer "live").
function waitForUploadQueueToDrain() {
  return new Promise((resolve) => {
    const check = () => {
      if (!state.uploading && state.uploadQueue.length === 0) resolve();
      else setTimeout(check, 300);
    };
    check();
  });
}

function showAsrWarning(message) {
  const el = document.getElementById("asrWarning");
  el.textContent = `Ses tanıma çalışmıyor: ${message} (Kayıt devam ediyor, ama konuşmalar metne dönüşmüyor.)`;
  el.hidden = false;
}
function hideAsrWarning() {
  document.getElementById("asrWarning").hidden = true;
}

async function startRecording() {
  micError.hidden = true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    micError.textContent = "Bu tarayıcıda mikrofon erişimi desteklenmiyor.";
    micError.hidden = false;
    return;
  }
  try {
    state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    micError.textContent = "Mikrofona erişilemedi. Lütfen tarayıcı izinlerini kontrol edin.";
    micError.hidden = false;
    return;
  }
  state.recording = true;
  recordingLoop(state.mediaStream);
}

function stopRecording() {
  state.recording = false;
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach((t) => t.stop());
    state.mediaStream = null;
  }
}

document.getElementById("endBtn").addEventListener("click", async () => {
  const btn = document.getElementById("endBtn");
  btn.disabled = true;
  stopRecording(); // no new chunks — but let already-queued ones finish uploading
  if (state.uploading || state.uploadQueue.length > 0) {
    btn.textContent = "Kalan parçalar işleniyor…";
    await waitForUploadQueueToDrain(); // polling (below) keeps showing them as they arrive
  }
  btn.textContent = "Bitiriliyor…";
  stopPolling();
  stopRecTimer();
  try {
    await api.endMeeting(state.meetingId);
    const final = await api.getMeeting(state.meetingId);
    hydrateFromMeeting(final);
    enterEndedScreen();
  } catch (err) {
    alert(err.message || "Toplantı bitirilemedi.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Toplantıyı Bitir";
  }
});

/* ---------------------------------------------------------------------- *
 * Tutanak (ended) screen
 * ---------------------------------------------------------------------- */

function fmtDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("tr-TR", { dateStyle: "long", timeStyle: "short" });
}
function fmtTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("tr-TR", { timeStyle: "short" });
}

function enterEndedScreen() {
  const m = state.meetingMeta;
  document.getElementById("docTitle").textContent = m.title;
  document.getElementById("docMeta").textContent =
    `${fmtDateTime(m.started_at)}${m.ended_at ? " – " + fmtTime(m.ended_at) : ""} · ${m.participants.length} Katılımcı`;
  document.getElementById("docParticipants").textContent =
    m.participants.map((p) => p.display_name).join(", ") || "—";

  const transcriptEl = document.getElementById("docTranscript");
  transcriptEl.innerHTML = "";
  if (m.segments.length === 0) {
    const p = document.createElement("p");
    p.className = "doc-body";
    p.textContent = "Bu toplantıda kayıtlı konuşma yok.";
    transcriptEl.appendChild(p);
  } else {
    m.segments.forEach((seg) => {
      const p = document.createElement("div");
      p.className = "doc-body";
      const strong = document.createElement("strong");
      strong.textContent = (seg.participant_name || "Konuşmacı belirsiz") + ": ";
      p.appendChild(strong);
      p.appendChild(document.createTextNode(seg.text));
      transcriptEl.appendChild(p);
    });
  }

  document.getElementById("keyBtn").hidden = true;
  showScreen("s3");
}

document.getElementById("newMeetingBtn").addEventListener("click", () => {
  state.meetingId = null;
  state.editToken = null;
  state.agendaItems = [];
  state.participants = [];
  state.segments = [];
  state.lastSegmentId = 0;
  state.activeSpeakerId = null;
  state.currentAgendaIdx = 0;
  state.meetingMeta = null;

  document.getElementById("titleInput").value = "";
  renderAgendaList();
  renderParticipantList();
  showScreen("s1");
});
