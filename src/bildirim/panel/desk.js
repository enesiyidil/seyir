const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.search).get("t") || "";
const url = path => path + "?t=" + encodeURIComponent(token);
const view = $("view");
let disposed = false, frameURL = "", lastFrame = 0, refreshTimer;

async function request(path, options) {
  const res = await fetch(url(path), {cache:"no-store", ...options});
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || "Bağlantı kesildi. Telegram’dan ekranı yeniden aç.");
  }
  return res;
}
function postJSON(path, data) {
  return request(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
}

async function refresh() {
  try {
    const res = await request("/frame.jpg", {signal:AbortSignal.timeout(10000)});
    const blob = await res.blob();
    if (disposed) return;
    const next = URL.createObjectURL(blob);
    const image = new Image();
    image.src = next;
    try { await image.decode(); }
    catch (err) { URL.revokeObjectURL(next); throw err; }
    if (disposed) { URL.revokeObjectURL(next); return; }
    view.src = next;
    if (frameURL) URL.revokeObjectURL(frameURL);
    frameURL = next;
    lastFrame = Date.now();
    $("frameHint").hidden = true;
    $("connection").textContent = "Ekran bağlı";
    $("connection").className = "status ok";
  } catch (err) {
    lastFrame = 0;
    $("connection").textContent = "Görüntü kesildi";
    $("connection").className = "status";
    $("frameHint").hidden = false;
    $("frameHint").textContent = err.message || "Mac ekranı alınamadı.";
  } finally {
    if (!disposed) refreshTimer = setTimeout(refresh, 480);
  }
}
refresh();

let controlling = false;
async function control(data) {
  if (controlling) return false;
  if (!lastFrame || Date.now() - lastFrame > 7000) {
    $("controlState").textContent = "Güncel ekran görüntüsü bekleniyor.";
    return false;
  }
  controlling = true;
  $("controlState").textContent = "Mac’e iletiliyor…";
  try {
    await postJSON("/control", data);
    $("controlState").textContent = "Girdi Mac’e iletildi.";
    return true;
  } catch (err) {
    $("controlState").textContent = err.message;
    return false;
  } finally { controlling = false; }
}
function point(ev) {
  const rect = view.getBoundingClientRect();
  const x = (ev.clientX - rect.left) / rect.width, y = (ev.clientY - rect.top) / rect.height;
  return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? {x,y} : null;
}
let gesture;
view.oncontextmenu = ev => ev.preventDefault();
view.onpointerdown = ev => {
  if (!ev.isPrimary || (ev.button !== 0 && ev.button !== 2)) return;
  gesture = {id:ev.pointerId, start:point(ev), op:ev.button === 2 ? "right" : $("pointerMode").value};
  view.setPointerCapture(ev.pointerId);
};
view.onpointercancel = () => { gesture = null; };
view.onpointerup = ev => {
  if (!gesture || ev.pointerId !== gesture.id) return;
  const {start, op} = gesture, end = point(ev);
  gesture = null;
  if (start && end) control({op, ...start, endX:end.x, endY:end.y});
};
document.querySelectorAll("[data-key]").forEach(button => {
  button.onclick = () => control({op:"key", name:button.dataset.key});
});
document.querySelectorAll("[data-scroll]").forEach(button => {
  button.onclick = () => control({op:"scroll", dy:Number(button.dataset.scroll)});
});
$("typeForm").onsubmit = async ev => {
  ev.preventDefault();
  const field = $("macText"), text = field.value;
  if (await control({op:"type", text}) && field.value === text) field.value = "";
};

function turn(mine, value) {
  const box = document.createElement("div"), who = document.createElement("small");
  box.className = mine ? "turn mine" : "turn reply";
  who.textContent = mine ? "Sen" : "Asistan";
  const content = document.createElement("span");
  content.textContent = value;
  box.append(who, content);
  $("log").append(box);
  $("log").scrollTop = $("log").scrollHeight;
  return content;
}
function wavBlob(pcm, rate) {
  const bytes = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(bytes);
  function tag(at, s) { for (let i=0; i<s.length; i++) v.setUint8(at+i, s.charCodeAt(i)); }
  tag(0,"RIFF"); v.setUint32(4, bytes.byteLength-8, true); tag(8,"WAVE"); tag(12,"fmt ");
  v.setUint32(16,16,true); v.setUint16(20,1,true); v.setUint16(22,1,true);
  v.setUint32(24,rate,true); v.setUint32(28,rate*2,true); v.setUint16(32,2,true);
  v.setUint16(34,16,true); tag(36,"data"); v.setUint32(40,pcm.length*2,true);
  for (let i=0; i<pcm.length; i++) v.setInt16(44+i*2, Math.max(-1,Math.min(1,pcm[i]))*32767,true);
  return new Blob([bytes], {type:"audio/wav"});
}

let audio, stream, source, gate, player, active = false, waiting = false, epoch = 0;
const mic = $("mic"), state = $("voiceState");
function unlockAudio() {
  audio ??= new AudioContext();
  return audio.resume();
}
function stopVoice() {
  active = false;
  epoch++;
  if (gate) { gate.port.onmessage = null; gate.disconnect(); }
  source?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  if (player) player.stop();
  source = stream = gate = player = null;
  mic.setAttribute("aria-pressed","false");
  mic.textContent = "Konuşmayı aç";
  state.textContent = "Mikrofon kapalı";
}
function listen() {
  if (!active || !gate || waiting) return;
  gate.port.postMessage("listen");
  state.textContent = "Dinliyor…";
}
async function playReply(encoded, id) {
  if (!encoded) throw new Error("Sesli yanıt üretilemedi.");
  const bytes = Uint8Array.from(atob(encoded), ch => ch.charCodeAt(0));
  const buffer = await audio.decodeAudioData(bytes.buffer);
  if (id !== epoch || disposed) return;
  if (audio.state !== "running") throw new Error("Ses çıkışı duraklatıldı.");
  const node = audio.createBufferSource();
  node.buffer = buffer;
  node.connect(audio.destination);
  player = node;
  await new Promise(resolve => {
    node.onended = resolve;
    node.start();
  });
  node.disconnect();
  if (player === node) player = null;
}
async function ask(question, blob) {
  if (waiting) return;
  waiting = true;
  const id = epoch, mine = turn(true, blob ? "Sesli mesaj" : question), reply = turn(false,"Yanıt bekleniyor…");
  $("chat").querySelector("button").disabled = true;
  gate?.port.postMessage("pause");
  if (active) state.textContent = "Yanıt hazırlanıyor…";
  try {
    const response = blob ? await request("/talk", {method:"POST", body:blob}) : await postJSON("/chat",{text:question});
    const data = await response.json();
    mine.textContent = data.heard || question;
    reply.textContent = data.reply;
    $("log").scrollTop = $("log").scrollHeight;
    if (id !== epoch) return;
    if (active) state.textContent = "Asistan konuşuyor…";
    try { await playReply(data.wav, id); }
    catch { reply.append(document.createTextNode(" (Ses oynatılamadı.)")); }
  } catch (err) {
    reply.textContent = err.message;
    if (active && id === epoch) stopVoice();
  } finally {
    waiting = false;
    $("chat").querySelector("button").disabled = false;
    listen();
  }
}
let loadedWorklet;
mic.onclick = async () => {
  if (active) { stopVoice(); return; }
  active = true;
  const id = ++epoch;
  mic.setAttribute("aria-pressed","true");
  mic.textContent = "Konuşmayı kapat";
  state.textContent = "Mikrofon izni bekleniyor…";
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode)
      throw new Error("Bağlantıyı HTTPS üzerinden Safari veya Chrome’da aç.");
    await unlockAudio();
    loadedWorklet ??= audio.audioWorklet.addModule("/speech-gate.js").catch(err => { loadedWorklet = null; throw err; });
    await loadedWorklet;
    if (id !== epoch) return;
    const acquired = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    if (id !== epoch) { acquired.getTracks().forEach(track => track.stop()); return; }
    stream = acquired;
    stream.getAudioTracks()[0].onended = () => { if (id === epoch) stopVoice(); };
    source = audio.createMediaStreamSource(stream);
    gate = new AudioWorkletNode(audio, "speech-gate");
    source.connect(gate);
    gate.connect(audio.destination); // The processor outputs silence.
    gate.port.onmessage = ({data}) => {
      if (!active || waiting || id !== epoch) return;
      if (data.pcm) ask("", wavBlob(data.pcm, data.rate));
      else state.textContent = data.state === "speech" ? "Seni duyuyorum…" : "Dinliyor…";
    };
    if (waiting) state.textContent = "Yanıt bekleniyor…";
    listen();
  } catch (err) {
    if (id !== epoch) return;
    stopVoice();
    state.textContent = err.name === "NotAllowedError" ? "Mikrofon izni verilmedi." : err.message;
  }
};
$("chat").onsubmit = async ev => {
  ev.preventDefault();
  const field = $("question"), question = field.value.trim();
  if (!question || waiting) return;
  try { await unlockAudio(); } catch { /* Text replies still work. */ }
  field.value = "";
  ask(question, null);
};
addEventListener("pagehide", () => {
  disposed = true;
  clearTimeout(refreshTimer);
  stopVoice();
  if (frameURL) URL.revokeObjectURL(frameURL);
  navigator.sendBeacon(url("/bye"));
});
