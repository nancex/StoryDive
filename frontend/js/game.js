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
  // Hide hint on last paragraph or when only one paragraph
  var isLast = (paragraphIndex >= paragraphQueue.length - 1);
  document.getElementById('dialog-hint').style.display = (isAutoPlaying || isLast) ? 'none' : 'block';
  // Avoid duplicate: don't push if this paragraph is already the last item in history
  if (storyHistory.length === 0 || storyHistory[storyHistory.length - 1] !== p) {
    storyHistory.push(p);
  }
  // Enable input immediately when the last paragraph is shown
  if (isLast) {
    setActionInputDisabled(false);
  } else {
    setActionInputDisabled(true);
  }
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

// ── KEYBOARD SHORTCUTS ──
document.addEventListener('keydown', function(e) {
  // Only active in game stage
  var stage = document.getElementById('game-stage');
  if (!stage || !stage.classList.contains('active')) return;

  var input = document.getElementById('action-input');
  var inputFocused = (document.activeElement === input);

  if (e.key === ' ' && !inputFocused) {
    // Space: advance paragraph when action input is not focused
    e.preventDefault();
    advanceParagraph();
  } else if (e.key === 'Enter' && inputFocused) {
    // Enter: submit action when input is focused
    var btn = document.getElementById('btn-submit');
    if (!btn.disabled && !_submitting) {
      e.preventDefault();
      submitAction();
    }
  }
});

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

var _submitting = false;

async function submitAction() {
  if (_submitting) return;
  var input = document.getElementById('action-input');
  var text = input.value.trim();
  if (!text) return;
  if (!await checkApiHealth()) return;
  _submitting = true;
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
    _submitting = false;
    stopGenTimer(btn, origText);
    setActionInputDisabled(false);
    return;
  }
  var data = await res.json();
  stopGenTimer(btn, origText);
  if (data.error) {
    showToast('生成失败：' + data.error, 'error');
    _submitting = false;
    setActionInputDisabled(false);
    return;
  }
  paragraphQueue = data.paragraph_queue || [];
  if (!paragraphQueue.length) {
    showToast('LLM 未返回有效内容，请重试', 'error');
    _submitting = false;
    setActionInputDisabled(false);
    return;
  }
  paragraphIndex = 0;
  _submitting = false;
  setActionInputDisabled(true);
  renderParagraph();
  actionMode = 'normal';
  updateToggleStates();
  // Reload memo/refs in case LLM updated them via tools
  reloadMemoAndRefs();
}

