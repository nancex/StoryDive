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
  document.getElementById('bm-start-btn').textContent = '开始新剧本';
  document.getElementById('book-modal').classList.add('active');
}

function closeBookModal() { document.getElementById('book-modal').classList.remove('active'); }

async function openSavePicker(bookId, saves) {
  currentBookId = bookId;
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
    currentMemo = data.memo || '';
    currentReferenceSections = data.reference_sections || [];
    document.getElementById('stage-title').textContent = data.book_title;
    loadAvailableSections();
    renderParagraph();
  } catch(e) {
    showToast('加载存档失败：' + e.message, 'error');
    exitStage();
  }
}



async function startBook() {
  if (!currentBookId) return;
  if (!await checkApiHealth()) return;
  if (!await checkLlmHealth()) return;
  var startBtn = document.getElementById("bm-start-btn");
  startGenTimer(startBtn);
  var res;
  try {
    res = await fetch(API + '/books/' + currentBookId + '/start', { method: 'POST' });
  } catch(e) {
    showToast('请求失败：' + e.message, 'error');
    stopGenTimer(startBtn, '开始新剧本');
    return;
  }
  var data = await res.json();
  if (data.error || res.status >= 400) {
    stopGenTimer(startBtn, '开始新剧本');
    showToast('生成失败：' + (data.error || data.detail || '未知错误'), 'error');
    return;
  }
  currentSaveId = data.save_id;
  storyHistory = [];
  currentMemo = data.memo || '';
  currentReferenceSections = data.reference_sections || [];
  _streamingQueue = [];
  _streamingCurrentIdx = 0;
  _streamingDone = false;
  _streamAbort = null;
  _lastHistoryIdx = -1;
  paragraphQueue = [];
  paragraphIndex = 0;
  loadAvailableSections();
  // Stay on browse view until first content arrives from streaming
  await submitAction('', false, false, false, data.book_title, true, startBtn);
}

async function continueBook() {
  closeBookModal();
  var saves = window._currentBookSaves || [];
  if (saves.length > 0) await openSavePicker(currentBookId, saves);
}


