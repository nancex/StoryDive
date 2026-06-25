// ── MEMO & REFERENCE MANAGEMENT ──
async function reloadMemoAndRefs() {
  if (!currentSaveId) return;
  try {
    var res = await fetch(API + '/saves/' + currentSaveId);
    var data = await res.json();
    currentMemo = data.memo || '';
    currentReferenceSections = data.reference_sections || [];
  } catch(e) {}
}

async function loadAvailableSections() {
  if (!currentBookId) return;
  try {
    var res = await fetch(API + '/books/' + currentBookId + '/sections');
    var data = await res.json();
    availableSections = data.sections || [];
  } catch(e) {}
}

function openMemoPanel() {
  var ta = document.getElementById('memo-textarea');
  var modal = document.getElementById('memo-modal');
  if (!ta || !modal) return;
  ta.value = currentMemo || '';
  modal.classList.add('active');
}

function closeMemoPanel() {
  document.getElementById('memo-modal').classList.remove('active');
}

async function saveMemo() {
  var text = document.getElementById('memo-textarea').value;
  try {
    var res = await fetch(API + '/saves/' + currentSaveId + '/memo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memo: text })
    });
    if (res.ok) {
      currentMemo = text;
      showToast('备忘录已保存', 'success');
      closeMemoPanel();
    } else {
      showToast('保存失败', 'error');
    }
  } catch(e) {
    showToast('保存失败：' + e.message, 'error');
  }
}

function openRefsPanel() {
  var container = document.getElementById('refs-checkboxes');
  var modal = document.getElementById('refs-modal');
  if (!container || !modal) return;
  var sections = availableSections || [];
  container.innerHTML = sections.map(function(s) {
    var checked = currentReferenceSections.indexOf(s) >= 0 ? ' checked' : '';
    return '<label class="flex items-center gap-2 p-2 hover:bg-surface-800 rounded cursor-pointer">' +
      '<input type="checkbox" value="' + escHtml(s) + '" class="ref-checkbox"' + checked + '>' +
      '<span class="text-sm text-surface-300">' + escHtml(s) + '</span></label>';
  }).join('');
  modal.classList.add('active');
}

function closeRefsPanel() {
  document.getElementById('refs-modal').classList.remove('active');
}

async function saveReferenceSections() {
  var checkboxes = document.querySelectorAll('.ref-checkbox:checked');
  var sections = Array.from(checkboxes).map(function(cb) { return cb.value; });
  try {
    var res = await fetch(API + '/saves/' + currentSaveId + '/reference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sections: sections })
    });
    if (res.ok) {
      currentReferenceSections = sections;
      showToast('参考小节已更新（将在下次生成时生效）', 'success');
      closeRefsPanel();
    } else {
      showToast('保存失败', 'error');
    }
  } catch(e) {
    showToast('保存失败：' + e.message, 'error');
  }
}
