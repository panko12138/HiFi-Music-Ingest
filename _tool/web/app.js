'use strict';

const $ = (sel, root = document) => root.querySelector(sel);

function esc(s) {
  return (s === null || s === undefined ? '' : String(s))
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtSize(n) {
  n = Number(n || 0);
  if (!n) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + units[i];
}

const LOSSY = new Set(['mp3', 'm4a', 'aac', 'ogg', 'wma', 'ape']);

const state = { candidates: [], tasks: new Map() };

async function postJSON(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { data = { error: 'HTTP ' + r.status }; }
  return data;
}

/* ---------------------------------------------------------------- 检索 */
async function doSearch() {
  const query = $('#query').value.trim();
  if (!query) return;
  const btn = $('#searchBtn');
  btn.disabled = true;
  $('#searchHint').textContent = '检索中（多来源并发，最多等待约 20 秒）…';
  try {
    const data = await postJSON('/api/search', { query });
    state.candidates = data.candidates || [];
    if (data.source_ok === false) {
      $('#engineState').textContent = '检索引擎：不可用';
      $('#engineState').className = 'tag bad';
    } else if (data.source_ok === true) {
      $('#engineState').textContent = '检索引擎：就绪';
      $('#engineState').className = 'tag ok';
    }
    renderCandidates();
    const notes = (data.errors || []).slice();
    if (data.error) notes.unshift(data.error);
    if (!notes.length && !state.candidates.length) notes.push('未找到候选（可尝试手动直链兜底）');
    $('#searchHint').textContent = notes.join('；');
  } catch (e) {
    $('#searchHint').textContent = '请求失败：' + e;
  } finally {
    btn.disabled = false;
  }
}

function renderCandidates() {
  const tbody = $('#candTable tbody');
  const rows = state.candidates.map((c, i) => {
    const lossless = c.format === 'flac' || c.format === 'wav';
    const cls = lossless ? 'pill lossless' : 'pill lossy';
    const note = lossless ? '无损' : '有损';
    return `<tr>
      <td>${esc(c.source)}</td>
      <td>${esc(c.artist)}</td>
      <td>${esc(c.title)}</td>
      <td>${esc(c.album)}</td>
      <td><span class="pill ${lossless ? 'lossless' : 'lossy'}">${esc((c.format || '?').toUpperCase())}</span></td>
      <td>${fmtSize(c.size)}</td>
      <td>${c.bitrate ? c.bitrate + 'k' : '—'}</td>
      <td>${c.quality_score || 0}</td>
      <td>${esc(note)}</td>
      <td><button class="btn tiny" data-i="${i}">下载</button></td>
    </tr>`;
  }).join('');
  tbody.innerHTML = rows || `<tr><td colspan="10" class="empty">暂无候选</td></tr>`;
  $('#candCount').textContent = state.candidates.length ? `（${state.candidates.length} 条）` : '';
  tbody.querySelectorAll('button[data-i]').forEach(b => {
    b.addEventListener('click', () => enqueue(state.candidates[Number(b.dataset.i)]));
  });
}

async function enqueue(candidate) {
  if (!candidate) return;
  const data = await postJSON('/api/download', { candidate });
  if (data.task_id) await loadQueue();
  else $('#searchHint').textContent = data.msg || '入队失败';
}

/* ---------------------------------------------------------------- 队列 */
function statusPill(status) {
  const map = {
    pending: ['muted', '等待'], running: ['', '进行中'], paused: ['warn', '已暂停'],
    done: ['ok', '完成'], failed: ['err', '失败'], skipped: ['warn', '重复/跳过'],
    canceled: ['muted', '已取消'],
  };
  const [cls, label] = map[status] || ['muted', status];
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

function barClass(status) {
  if (status === 'done') return 'bar done';
  if (status === 'failed') return 'bar failed';
  return 'bar';
}

function taskActions(t) {
  const out = [];
  if (t.status === 'running' || t.status === 'pending') {
    out.push(`<button class="btn tiny ghost" data-act="pause" data-id="${t.id}">暂停</button>`);
    out.push(`<button class="btn tiny ghost" data-act="cancel" data-id="${t.id}">取消</button>`);
  } else if (['paused', 'canceled', 'failed'].includes(t.status)) {
    out.push(`<button class="btn tiny ghost" data-act="resume" data-id="${t.id}">恢复</button>`);
  }
  return out.join(' ');
}

function renderTasks() {
  const tbody = $('#queueTable tbody');
  const tasks = Array.from(state.tasks.values());
  tbody.innerHTML = tasks.map(t => {
    const song = `${t.candidate && t.candidate.artist ? t.candidate.artist + ' - ' : ''}${(t.candidate && t.candidate.title) || t.query || ''}`;
    return `<tr>
      <td>${statusPill(t.status)}</td>
      <td class="wrap">${esc(song)}</td>
      <td><div class="${barClass(t.status)}"><i style="width:${Math.max(0, Math.min(100, t.percent || 0))}%"></i></div>
          <span class="muted">${(t.percent || 0).toFixed(0)}%</span></td>
      <td>${esc(t.speed || '—')}</td>
      <td class="wrap">${esc(t.msg || '')}</td>
      <td>${taskActions(t)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="6" class="empty">队列为空</td></tr>`;
  $('#queueCount').textContent = tasks.length ? `（${tasks.length} 项）` : '';
  tbody.querySelectorAll('button[data-act]').forEach(b => {
    b.addEventListener('click', async () => {
      await postJSON('/api/queue/action', { task_id: b.dataset.id, action: b.dataset.act });
      await loadQueue();
    });
  });
}

async function loadQueue() {
  const r = await fetch('/api/queue');
  const data = await r.json();
  state.tasks = new Map((data.tasks || []).map(t => [t.id, t]));
  renderTasks();
}

/* ---------------------------------------------------------------- 日志 */
async function loadLog() {
  const r = await fetch('/api/log?limit=200');
  const data = await r.json();
  const rows = (data.results || []).slice().reverse().map(x => {
    const cls = x.status === '成功' ? 'ok' : (x.status === '失败' ? 'err' : 'warn');
    return `<tr>
      <td>${esc(x.time)}</td><td>${esc(x.song)}</td>
      <td><span class="pill ${cls}">${esc(x.status)}</span></td>
      <td class="wrap">${esc(x.reason)}</td><td class="wrap">${esc(x.path)}</td>
    </tr>`;
  }).join('');
  $('#logTable tbody').innerHTML = rows || `<tr><td colspan="5" class="empty">暂无记录</td></tr>`;
  $('#logCount').textContent = (data.results || []).length ? `（${(data.results || []).length} 条）` : '';
}

/* ---------------------------------------------------------------- SSE */
function startStream() {
  const es = new EventSource('/api/queue/stream');
  es.onmessage = ev => {
    if (!ev.data) return;
    let payload;
    try { payload = JSON.parse(ev.data); } catch (e) { return; }
    if (payload.type === 'task' && payload.task) {
      state.tasks.set(payload.task.id, payload.task);
      renderTasks();
    } else if (payload.type === 'result') {
      loadLog();
    }
  };
  es.onerror = () => { /* 浏览器会自动重连 */ };
}

/* ---------------------------------------------------------------- 兜底 / 批量 / 校验 */
async function addManual() {
  const url = $('#manualUrl').value.trim();
  if (!url) return;
  const data = await postJSON('/api/manual', { url });
  $('#searchHint').textContent = data.msg || '';
  if (data.candidates && data.candidates.length) {
    state.candidates = data.candidates.concat(state.candidates);
    renderCandidates();
  }
}

async function addLocal() {
  const path = $('#localPath').value.trim();
  if (!path) return;
  const data = await postJSON('/api/manual', { local_path: path });
  $('#searchHint').textContent = data.msg || '';
  if (data.candidates && data.candidates.length) {
    state.candidates = data.candidates.concat(state.candidates);
    renderCandidates();
  }
}

async function submitBatch(content, filename) {
  const form = new FormData();
  form.append('file', new Blob([content], { type: 'text/plain' }), filename);
  const r = await fetch('/api/batch', { method: 'POST', body: form });
  const data = await r.json().catch(() => ({}));
  $('#searchHint').textContent = data.msg || '批量提交完成';
  await loadQueue();
}

async function doVerify() {
  const out = $('#verifyOut');
  out.hidden = false;
  out.textContent = '校验中…';
  const data = await postJSON('/api/verify', {});
  const lines = [`清单记录：${data.total} 条`, `错误：${(data.errors || []).length}    警告：${(data.warnings || []).length}`];
  (data.errors || []).forEach(m => lines.push('[错误] ' + m));
  (data.warnings || []).forEach(m => lines.push('[警告] ' + m));
  out.textContent = lines.join('\n') || '无问题';
}

/* ---------------------------------------------------------------- 绑定 */
function bind() {
  $('#searchBtn').addEventListener('click', doSearch);
  $('#query').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  $('#manualUrlBtn').addEventListener('click', addManual);
  $('#localBtn').addEventListener('click', addLocal);
  $('#verifyBtn').addEventListener('click', doVerify);
  $('#batchFile').addEventListener('change', async e => {
    const f = e.target.files[0];
    if (!f) return;
    const text = await f.text();
    await submitBatch(text, f.name);
  });
  $('#batchTextBtn').addEventListener('click', async () => {
    const text = $('#batchText').value.trim();
    if (!text) return;
    await submitBatch(text, 'batch.txt');
  });
}

bind();
loadQueue();
loadLog();
startStream();
