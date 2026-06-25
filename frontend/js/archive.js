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
    currentBookId = data.book_id || currentBookId;
    currentMemo = data.memo || '';
    currentReferenceSections = data.reference_sections || [];
    loadAvailableSections();
    enterGameStage(data.book_title);
  } catch(e) {
    showToast('加载存档失败：' + e.message, 'error');
    return;
  }
}

async function deleteSave() {
  var confirmed = await showConfirm('删除存档', '确定要删除这个存档吗？此操作不可撤销。', '删除');
  if (!confirmed) return;
  await fetch(API + '/saves/' + currentSaveId, { method: 'DELETE' });
  closeSaveModal();
  showToast('存档已删除', 'success');
  loadSaves();
}
