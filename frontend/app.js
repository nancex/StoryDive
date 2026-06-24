// ── STATE ──
var API = 'http://localhost:8800/api';
var currentView = 'browse';
var currentBookId = null;
var currentSaveId = null;
var paragraphQueue = [];
var paragraphIndex = 0;
var storyHistory = [];
var longPressTimer = null;
var autoPlayInterval = null;
var isAutoPlaying = false;
var actionMode = 'normal';
var bookDetailCache = {};
var genStartTime = 0;
var genTimerInterval = null;

function startGenTimer(btn) {
  genStartTime = Date.now();
  btn.disabled = true;
  btn.textContent = '生成中 0s';
  clearInterval(genTimerInterval);
  genTimerInterval = setInterval(function() {
    var elapsed = Math.floor((Date.now() - genStartTime) / 1000);
    btn.textContent = '生成中 ' + elapsed + 's';
  }, 1000);
}

function stopGenTimer(btn, origText) {
  clearInterval(genTimerInterval);
  genTimerInterval = null;
  if (btn) {
    btn.textContent = origText || '发送';
    btn.disabled = false;
  }
}


// ── TOAST NOTIFICATION ──
function showToast(msg, type) {
  type = type || 'info';
  var t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('toast-visible'); t.style.opacity = '1'; t.style.transform = 'translate(-50%, 0)';
  if (type === 'error') t.style.background = '#dc2626';
  else if (type === 'success') t.style.background = '#16a34a';
  else t.style.background = '#4f46e5';
  clearTimeout(t._timeout);
  t._timeout = setTimeout(function() {
    t.classList.remove('toast-visible');
    t.style.opacity = '0';
    t.style.transform = 'translate(-50%, 16px)';
  }, 2000);
}

// ── CONFIRM DIALOG ──
var _confirmResolve = null;
function showConfirm(title, msg, okText) {
  okText = okText || '删除';
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-message').textContent = msg;
  document.getElementById('confirm-ok-btn').textContent = okText;
  document.getElementById('confirm-modal').classList.add('active');
  return new Promise(function(resolve) { _confirmResolve = resolve; });
}
function closeConfirm(result) {
  document.getElementById('confirm-modal').classList.remove('active');
  if (_confirmResolve) { var r = _confirmResolve; _confirmResolve = null; r(result); }
}

// ── API TEST ──
async function testApi(type) {
  var url, key, model;
  if (type === 'llm') {
    url = document.getElementById('cfg-llm-url').value;
    key = document.getElementById('cfg-llm-key').value;
    model = document.getElementById('cfg-llm-model').value;
  } else if (type === 'image') {
    url = document.getElementById('cfg-img-url').value;
    key = document.getElementById('cfg-img-key').value;
    model = document.getElementById('cfg-img-model').value;
  } else if (type === 'tts') {
    url = document.getElementById('cfg-tts').value;
  }

  if (!url) { showToast('请先输入 Base URL', 'error'); return; }
  if (type !== 'tts' && !key) { showToast('请先输入 API Key', 'error'); return; }

  var btn = document.getElementById('btn-test-' + type);
  var origText = btn.textContent;
  btn.textContent = '测试中…';
  btn.disabled = true;

  try {
    var apiUrl = url.replace(/\/+$/, '');
    var resp;
    if (type === 'tts') {
      resp = await fetch(apiUrl, { method: 'GET', signal: AbortSignal.timeout(5000) });
    } else {
      resp = await fetch(apiUrl + '/models', {
        headers: { 'Authorization': 'Bearer ' + key },
        signal: AbortSignal.timeout(8000)
      });
    }
    if (resp.ok) {
      showToast(type.toUpperCase() + ' API 连接成功！', 'success');
    } else {
      var txt = '';
      try { txt = await resp.text(); } catch(e) {}
      showToast(type.toUpperCase() + ' API 错误：' + resp.status + ' ' + txt.slice(0, 60), 'error');
    }
  } catch(e) {
    showToast(type.toUpperCase() + ' API 无法访问：' + e.message, 'error');
  }
  btn.textContent = origText;
  btn.disabled = false;
}

// ── LLM API HEALTH CHECK ──
async function checkLlmHealth() {
  try {
    var resp = await fetch(API + '/settings');
    var s = await resp.json();
    var key = s.llm_api_key || '';
    if (!key || key === 'sk-placeholder') return true;
    var url = (s.llm_base_url || 'https://api.openai.com/v1').replace(/\/+$/, '');
    var testResp = await fetch(url + '/models', {
      headers: { 'Authorization': 'Bearer ' + key },
      signal: AbortSignal.timeout(8000)
    });
    if (testResp.ok) return true;
    showToast('大模型 API 错误：' + testResp.status + '，请检查 API 设置', 'error');
    return false;
  } catch(e) {
    showToast('大模型 API 无法访问：' + e.message + '，请检查 API 设置', 'error');
    return false;
  }
}


// ── VIEW SWITCHING ──
function switchView(view) {
  currentView = view;
  document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); });
  document.querySelectorAll('.nav-tab').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('view-' + view).classList.add('active');
  var tab = document.querySelector('[data-view="' + view + '"]');
  if (tab) tab.classList.add('active');
  if (view === 'browse') loadBooks();
  if (view === 'archive') loadSaves();
  if (view === 'settings') loadSettings();
}

// ── BROWSE ──
async function loadBooks() {
  var grid = document.getElementById('books-grid');
  grid.innerHTML = '<div class="text-surface-400 col-span-full text-center py-12">加载中……</div>';
  try {
    var res = await fetch(API + '/books');
    var data = await res.json();
    if (!data.books.length) {
      grid.innerHTML = '<div class="text-surface-400 col-span-full text-center py-12">暂无剧本</div>';
      return;
    }
    grid.innerHTML = data.books.map(function(b) {
      var tags = b.genre.map(function(g) { return '<span class="tag">' + escHtml(g) + '</span>'; }).join('');
      var saveInfo = b.save_count > 0 ? '<div class="text-primary-400 mt-1">' + b.save_count + ' 个存档</div>' : '';
      return '<div class="bg-surface-800 rounded-xl p-5 border border-surface-700/50 card-hover cursor-pointer" onclick="openBookModal(\'' + b.id + '\')">' +
        '<h3 class="text-lg font-bold text-white mb-2">' + escHtml(b.title) + '</h3>' +
        '<div class="flex gap-1 flex-wrap mb-3">' + tags + '</div>' +
        '<div class="text-surface-400 text-xs space-y-1">' +
          '<div>原作：' + escHtml(b.original_author) + '</div>' +
          '<div>主角：' + escHtml(b.protagonist) + '</div>' +
          saveInfo +
        '</div>' +
      '</div>';
    }).join('');
  } catch(e) {
    grid.innerHTML = '<div class="text-red-400 col-span-full text-center py-12">加载失败：' + escHtml(e.message) + '</div>';
  }
}

async function openBookModal(bookId) {
  currentBookId = bookId;
  if (!bookDetailCache[bookId]) {
    var res = await fetch(API + '/books/' + bookId);
    bookDetailCache[bookId] = await res.json();
  }
  var b = bookDetailCache[bookId];
  document.getElementById('bm-title').textContent = b.title;
  document.getElementById('bm-tags').innerHTML = b.genre.map(function(g) { return '<span class="tag">' + escHtml(g) + '</span>'; }).join('');
  document.getElementById('bm-oauthor').textContent = b.original_author;
  document.getElementById('bm-author').textContent = b.script_author;
  document.getElementById('bm-date').textContent = b.upload_date;
  document.getElementById('bm-protagonist').textContent = b.protagonist;
  document.getElementById('bm-desc').textContent = b.description;
  var contBtn = document.getElementById('bm-continue-btn');
  var savesRes = await fetch(API + '/saves');
  var savesData = await savesRes.json();
  var bookSaves = savesData.saves.filter(function(s) { return s.book_id === bookId; });
  window._currentBookSaves = bookSaves;
  if (bookSaves.length > 0) {
    contBtn.style.display = 'inline-block';
    contBtn.textContent = '继续剧本 (' + bookSaves.length + ')';
    contBtn.onclick = async function() { closeBookModal(); await openSavePicker(bookId, bookSaves); };
  } else {
    contBtn.style.display = 'none';
  }
  document.getElementById('book-modal').classList.add('active');
}

function closeBookModal() { document.getElementById('book-modal').classList.remove('active'); }

async function openSavePicker(bookId, saves) {
  currentSaveId = saves[0].id;
  if (!await checkApiHealth()) return;
  if (!await checkLlmHealth()) return;
  enterGameStage(saves[0].book_title);
  document.getElementById('dialog-text').innerHTML = '<span class="text-surface-400">加载存档中……</span>';
  document.getElementById('dialog-speaker').textContent = '';
  document.getElementById('dialog-hint').style.display = 'none';
  setActionInputDisabled(true);
  try {
    var res = await fetch(API + '/saves/' + currentSaveId + '/continue', { method: 'POST' });
    var data = await res.json();
    var allPars = data.full_history || [];
    storyHistory = allPars.slice();
    // Show only the last paragraph, wait for player action
    if (allPars.length > 0) {
      paragraphQueue = [allPars[allPars.length - 1]];
    } else {
      paragraphQueue = [{'type':'narration','text':'[Empty story]'}];
    }
    paragraphIndex = 0;
    document.getElementById('stage-title').textContent = data.book_title;
    renderParagraph();
  } catch(e) {
    showToast('加载存档失败：' + e.message, 'error');
    exitStage();
  }
}


// ── API HEALTH CHECK ──
async function checkApiHealth() {
  try {
    var resp = await fetch(API + '/books', { signal: AbortSignal.timeout(5000) });
    if (resp.ok) return true;
    showToast('后端 API 错误：' + resp.status, 'error');
    return false;
  } catch(e) {
    showToast('后端 API 无法访问，请先启动服务器', 'error');
    return false;
  }
}
async function startBook() {
  if (!currentBookId) return;
  if (!await checkApiHealth()) return;
  if (!await checkLlmHealth()) return;
  var startBtn = document.getElementById('bm-start-btn');
  startGenTimer(startBtn);
  var res;
  try {
    res = await fetch(API + '/books/' + currentBookId + '/start', { method: 'POST' });
  } catch(e) {
    showToast('请求失败：' + e.message, 'error');
    stopGenTimer(document.getElementById('bm-start-btn'), '开始新剧本');
    return;
  }
  var data = await res.json();
  stopGenTimer(document.getElementById('bm-start-btn'), '开始新剧本');
  closeBookModal();
  currentSaveId = data.save_id;
  paragraphQueue = data.paragraph_queue;
  paragraphIndex = 0;
  storyHistory = [];
  enterGameStage(data.book_title);
}

async function continueBook() {
  closeBookModal();
  var saves = window._currentBookSaves || [];
  if (saves.length > 0) await openSavePicker(currentBookId, saves);
}

// ── ARCHIVE ──
async function loadSaves() {
  var grid = document.getElementById('saves-grid');
  grid.innerHTML = '<div class="text-surface-400 col-span-full text-center py-12">加载中……</div>';
  try {
    var res = await fetch(API + '/saves');
    var data = await res.json();
    if (!data.saves.length) {
      grid.innerHTML = '<div class="text-surface-400 col-span-full text-center py-12">暂无存档</div>';
      return;
    }
    grid.innerHTML = data.saves.map(function(s) {
      var previews = s.preview.map(function(p) { return '<div class="preview-line">' + escHtml(p) + '</div>'; }).join('');
      return '<div class="bg-surface-800 rounded-xl p-5 border border-surface-700/50 card-hover cursor-pointer" onclick="openSaveModal(\'' + s.id + '\')">' +
        '<div class="flex items-start justify-between mb-2">' +
          '<div><h3 class="text-lg font-bold text-white">' + escHtml(s.book_title) + '</h3>' +
          '<div class="text-surface-400 text-xs mt-1">' + escHtml(s.last_modified.slice(0, 10)) + '</div></div>' +
          '<span class="text-xs text-surface-500">' + escHtml(s.id) + '</span>' +
        '</div>' +
        '<div class="space-y-1 mt-3">' + previews + '</div>' +
      '</div>';
    }).join('');
  } catch(e) {
    grid.innerHTML = '<div class="text-red-400 col-span-full text-center py-12">加载失败：' + escHtml(e.message) + '</div>';
  }
}

async function openSaveModal(saveId) {
  currentSaveId = saveId;
  var res = await fetch(API + '/saves/' + saveId);
  var s = await res.json();
  document.getElementById('sm-title').textContent = s.book_title;
  document.getElementById('sm-book').textContent = s.book_author;
  document.getElementById('sm-date').textContent = s.last_modified.slice(0, 10);
  var preview = document.getElementById('sm-preview');
  preview.innerHTML = s.story_preview.map(function(p) {
    var cls = p.type === 'dialogue' ? 'preview-line dialogue' : 'preview-line';
    var label = p.type === 'dialogue' ? '<span class="text-primary-400 text-xs">' + escHtml(p.speaker || '') + ':</span> ' : '';
    return '<div class="' + cls + '">' + label + escHtml(p.text) + '</div>';
  }).join('');
  document.getElementById('save-modal').classList.add('active');
}

function closeSaveModal() { document.getElementById('save-modal').classList.remove('active'); }

async function continueSave() {
  closeSaveModal();
  if (!await checkApiHealth()) return;
  if (!await checkLlmHealth()) return;
  var contBtn = document.querySelector('#save-modal .btn-primary');
  if (contBtn) { startGenTimer(contBtn); }
  try {
    var res = await fetch(API + '/saves/' + currentSaveId + '/continue', { method: 'POST' });
    var data = await res.json();
    stopGenTimer(contBtn, '继续故事');
    var allPars = data.full_history || [];
    storyHistory = allPars.slice();
    if (allPars.length > 0) {
      paragraphQueue = [allPars[allPars.length - 1]];
    } else {
      paragraphQueue = [{'type':'narration','text':'[Empty story]'}];
    }
    paragraphIndex = 0;
    enterGameStage(data.book_title);
  } catch(e) {
    showToast('加载存档失败：' + e.message, 'error');
    if (contBtn) stopGenTimer(contBtn, '继续故事');
  }
}

async function deleteSave() {
  var confirmed = await showConfirm('删除存档', '确定要删除此存档吗？此操作不可撤销。', '删除');
  if (!confirmed) return;
  await fetch(API + '/saves/' + currentSaveId, { method: 'DELETE' });
  closeSaveModal();
  showToast('存档已删除', 'success');
  loadSaves();
}

// ── SETTINGS ──
async function loadSettings() {
  try {
    var res = await fetch(API + '/settings');
    var s = await res.json();
    document.getElementById('cfg-llm-url').value = s.llm_base_url || '';
    document.getElementById('cfg-llm-key').value = s.llm_api_key || '';
    document.getElementById('cfg-llm-model').value = s.llm_model || '';
    document.getElementById('cfg-img-url').value = s.image_base_url || '';
    document.getElementById('cfg-img-key').value = s.image_api_key || '';
    document.getElementById('cfg-img-model').value = s.image_model || '';
    document.getElementById('cfg-tts').value = s.tts_endpoint || '';
    document.getElementById('cfg-llm-timeout').value = s.llm_timeout || 60;
  } catch(e) {}
}

async function saveSettings() {
  var data = {
    llm_base_url: document.getElementById('cfg-llm-url').value,
    llm_api_key: document.getElementById('cfg-llm-key').value,
    llm_model: document.getElementById('cfg-llm-model').value,
    image_base_url: document.getElementById('cfg-img-url').value,
    image_api_key: document.getElementById('cfg-img-key').value,
    image_model: document.getElementById('cfg-img-model').value,
    tts_endpoint: document.getElementById('cfg-tts').value,
    llm_timeout: parseInt(document.getElementById('cfg-llm-timeout').value) || 60
  };
  await fetch(API + '/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
  showToast('设置已保存', 'success');
}

// ── GAME STAGE ──
function enterGameStage(title) {
  document.getElementById('stage-title').textContent = title;
  document.getElementById('game-stage').classList.add('active');
  document.getElementById('dialog-speaker').textContent = '';
  document.getElementById('dialog-text').innerHTML = '';
  document.getElementById('dialog-hint').style.display = 'block';
  setActionInputDisabled(true);
  updateToggleStates();
  renderParagraph();
}

async function exitStage() {
  var confirmed = await showConfirm('退出游戏', '进度已自动保存，确定要退出吗？', '退出');
  if (!confirmed) return;
  stopAutoPlay();
  document.getElementById('game-stage').classList.remove('active');
  document.getElementById('history-overlay').style.display = 'none';
  paragraphQueue = [];
  storyHistory = [];
  switchView(currentView);
}

function renderParagraph() {
  if (paragraphIndex >= paragraphQueue.length) {
    document.getElementById('dialog-hint').style.display = 'none';
    setActionInputDisabled(false);
    return;
  }
  var p = paragraphQueue[paragraphIndex];
  if (p.type === 'dialogue') {
    document.getElementById('dialog-speaker').textContent = p.speaker || '';
  } else {
    document.getElementById('dialog-speaker').textContent = '';
  }
  document.getElementById('dialog-text').textContent = p.text;
  document.getElementById('dialog-hint').style.display = (isAutoPlaying || paragraphQueue.length <= 1) ? 'none' : 'block';
  // Avoid duplicate: don't push if this paragraph is already the last item in history
  if (storyHistory.length === 0 || storyHistory[storyHistory.length - 1] !== p) {
    storyHistory.push(p);
  }
  setActionInputDisabled(true);
}

function advanceParagraph() {
  if (isAutoPlaying) return;
  if (paragraphIndex >= paragraphQueue.length) return;
  paragraphIndex++;
  renderParagraph();
}

function setActionInputDisabled(disabled) {
  var input = document.getElementById('action-input');
  var btn = document.getElementById('btn-submit');
  input.disabled = disabled;
  btn.disabled = disabled;
  if (disabled) {
    input.placeholder = '（请先观看完当前队列的剧情……）';
  } else {
    input.placeholder = '输入你的行动或对话……';
    input.focus();
  }
}

// Long press auto-play
var dialogArea = document.getElementById('dialog-area');
dialogArea.addEventListener('pointerdown', function(e) {
  longPressTimer = setTimeout(function() {
    isAutoPlaying = true;
    document.getElementById('dialog-hint').style.display = 'none';
    autoPlayInterval = setInterval(function() {
      if (paragraphIndex >= paragraphQueue.length - 1) {
        stopAutoPlay();
        paragraphIndex++;
        renderParagraph();
        return;
      }
      paragraphIndex++;
      renderParagraph();
    }, 1500);
  }, 600);
});
dialogArea.addEventListener('pointerup', function() { clearTimeout(longPressTimer); });
dialogArea.addEventListener('pointerleave', function() { clearTimeout(longPressTimer); });

function stopAutoPlay() {
  isAutoPlaying = false;
  clearInterval(autoPlayInterval);
  autoPlayInterval = null;
  if (paragraphIndex < paragraphQueue.length) {
    document.getElementById('dialog-hint').style.display = 'block';
  }
}

// ── ACTION SUBMISSION ──
function updateActionMode() {
  var speak = document.getElementById('toggle-speak').checked;
  var regret = document.getElementById('toggle-regret').checked;
  var accel = document.getElementById('toggle-accelerate').checked;
  if (speak) {
    document.getElementById('toggle-regret').checked = false;
    document.getElementById('toggle-accelerate').checked = false;
    actionMode = 'speak';
  } else if (regret) {
    document.getElementById('toggle-speak').checked = false;
    document.getElementById('toggle-accelerate').checked = false;
    actionMode = 'regret';
  } else if (accel) {
    document.getElementById('toggle-speak').checked = false;
    document.getElementById('toggle-regret').checked = false;
    actionMode = 'accelerate';
  } else {
    actionMode = 'normal';
  }
  updateToggleStates();
}

function updateToggleStates() {
  document.getElementById('toggle-speak').checked = actionMode === 'speak';
  document.getElementById('toggle-regret').checked = actionMode === 'regret';
  document.getElementById('toggle-accelerate').checked = actionMode === 'accelerate';
}

async function submitAction() {
  var input = document.getElementById('action-input');
  var text = input.value.trim();
  if (!text) return;
  if (!await checkApiHealth()) return;
  input.value = '';
  var btn = document.getElementById('btn-submit');
  var origText = btn.textContent;
  startGenTimer(btn);

  if (actionMode === 'regret') {
    paragraphQueue = paragraphQueue.slice(0, paragraphIndex);
    paragraphIndex = paragraphQueue.length;
  }

  var res;
  try {
    res = await fetch(API + '/game/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        save_id: currentSaveId,
        action: text,
        mode: actionMode,
        target_paragraph_index: actionMode === 'regret' ? paragraphIndex : null
      })
    });
  } catch(e) {
    showToast('请求失败：' + e.message, 'error');
    stopGenTimer(btn, origText);
    return;
  }
  var data = await res.json();
  stopGenTimer(btn, origText);
  paragraphQueue = data.paragraph_queue;
  paragraphIndex = 0;
  setActionInputDisabled(true);
  renderParagraph();
  actionMode = 'normal';
  updateToggleStates();
}

// ── HISTORY ──
function toggleHistory() {
  var overlay = document.getElementById('history-overlay');
  if (overlay.style.display === 'none' || overlay.style.display === '') {
    overlay.style.display = 'flex';
    overlay.style.flexDirection = 'column';
    renderHistory();
  } else {
    overlay.style.display = 'none';
  }
}

function renderHistory() {
  var showSpeaker = document.getElementById('hist-show-speaker').checked;
  var content = document.getElementById('history-content');
  content.innerHTML = storyHistory.map(function(p) {
    if (p.type === 'dialogue') {
      if (showSpeaker) {
        return '<p style="margin-bottom:0.75rem"><span class="text-primary-400 font-bold">' + escHtml(p.speaker || '') + ': </span>' + escHtml(p.text) + '</p>';
      }
      return '<p style="margin-bottom:0.75rem">' + escHtml(p.text) + '</p>';
    }
    return '<p class="text-surface-300" style="margin-bottom:0.75rem">' + escHtml(p.text) + '</p>';
  }).join('');
  setTimeout(function() { content.scrollTop = content.scrollHeight; }, 50);
}

function exportHistory() {
  var text = storyHistory.map(function(p) {
    if (p.type === 'dialogue') return p.text;
    return p.text;
  }).join('\n\n');
  var blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'storydive_export.txt';
  a.click(); URL.revokeObjectURL(url);
}

// ── HELPERS ──
function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── INIT ──
loadBooks();
loadSettings();
