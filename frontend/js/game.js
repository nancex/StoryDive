// ── GAME STAGE ──
function enterGameStage(title) {
  document.getElementById('stage-title').textContent = title;
  document.getElementById('game-stage').classList.add('active');
  document.getElementById('dialog-speaker').textContent = '';
  document.getElementById('dialog-text').innerHTML = '';
  setActionInputDisabled(true);
  renderParagraph();
}

async function exitStage() {
  var confirmed = await showConfirm('退出游戏', '进度已自动保存，确定要退出吗？', '退出');
  if (!confirmed) return;
  stopAutoPlay();
  clearInterval(genTimerInterval); genTimerInterval = null;
  document.getElementById('game-stage').classList.remove('active');
  document.getElementById('history-overlay').style.display = 'none';
  paragraphQueue = [];
  storyHistory = [];
  _streamingQueue = [];
  _streamingCurrentIdx = 0;
  _streamingDone = false;
  _streamAbort = null;
  _lastHistoryIdx = -1;
  switchView(currentView);
}

// ── UNIFIED ARROW ──
var _lastHistoryIdx = -1;  // last paragraphQueue index added to storyHistory

function getArrowEl() {
  var el = document.getElementById('stream-arrow');
  if (!el) {
    el = document.createElement('div');
    el.id = 'stream-arrow';
    el.className = 'stream-arrow';
    el.textContent = '>';
    el.onclick = function() {
      if (!_streamingDone && (_streamAbort || _streamingQueue.length > 0)) {
        advanceStreamParagraph();
      } else {
        advanceParagraph();
      }
    };
    document.getElementById('dialog-area').appendChild(el);
  }
  return el;
}

function setArrowVisible(show) {
  var el = document.getElementById('stream-arrow');
  if (!el && !show) return;
  el = getArrowEl();
  el.style.display = show ? 'block' : 'none';
}

function removeArrow() {
  var el = document.getElementById('stream-arrow');
  if (el) el.remove();
}

// ── RENDER PARAGRAPH (non-streaming) ──
function renderParagraph() {
  if (paragraphIndex >= paragraphQueue.length) {
    setArrowVisible(false);
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

  // Add to storyHistory by index to avoid duplicates
  if (paragraphIndex > _lastHistoryIdx) {
    storyHistory.push({ type: p.type, text: p.text, speaker: p.speaker || undefined });
    _lastHistoryIdx = paragraphIndex;
  }

  var isLast = (paragraphIndex >= paragraphQueue.length - 1);
  if (isLast) {
    setArrowVisible(false);
    setActionInputDisabled(false);
  } else {
    setArrowVisible(true);
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
    setArrowVisible(false);
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
  if (paragraphIndex < paragraphQueue.length - 1) {
    setArrowVisible(true);
  }
}

// ── KEYBOARD SHORTCUTS ──
document.addEventListener('keydown', function(e) {
  var stage = document.getElementById('game-stage');
  if (!stage || !stage.classList.contains('active')) return;

  var input = document.getElementById('action-input');
  var inputFocused = (document.activeElement === input);

  if (e.key === ' ' && !inputFocused) {
    e.preventDefault();
    advanceParagraph();
  } else if (e.key === 'Enter' && inputFocused) {
    var btn = document.getElementById('btn-submit');
    if (!btn.disabled && !_submitting) {
      e.preventDefault();
      submitAction();
    }
  }
});

// ── ACTION SUBMISSION ──
function updateActionMode() {}
function updateToggleStates() {}

var _submitting = false;
var _streamingQueue = [];
var _streamingCurrentIdx = 0;
var _streamingDone = false;
var _streamAbort = null;

async function submitAction(text, speak, regret, accelerate, bookTitle, isFirstStart, startBtn) {
  // If called from UI (no params), read from DOM before any guards
  if (arguments.length === 0) {
    if (_submitting) return;
    var input = document.getElementById("action-input");
    text = input.value.trim();
    if (!text) return;
    if (!await checkApiHealth()) return;
    speak = document.getElementById("toggle-speak").checked;
    regret = document.getElementById("toggle-regret").checked;
    accelerate = document.getElementById("toggle-accelerate").checked;
    if (regret) {
      paragraphQueue = paragraphQueue.slice(0, paragraphIndex);
      paragraphIndex = paragraphQueue.length;
    }
  }

  if (!text && !isFirstStart) return;
  if (!text && isFirstStart) { /* first start, no user input */ }
  if (_submitting && !isFirstStart) return;
  _submitting = true;

  _streamingQueue = [];
  _streamingCurrentIdx = 0;
  _streamingDone = false;
  removeArrow();

  var btn = null;
  var origText = '';
  if (!isFirstStart) {
    var input = document.getElementById('action-input');
    input.value = '';
    btn = document.getElementById('btn-submit');
    origText = btn.textContent;
    startGenTimer(btn);
    setActionInputDisabled(true);
  }

  if (!isFirstStart) {
    paragraphQueue = [{ type: 'narration', text: '正在生成剧情……' }];
    paragraphIndex = 0;
    _lastHistoryIdx = -1;
    renderParagraphStreaming();
  }

  _streamAbort = new AbortController();
  var _firstStartEntered = false;

  try {
    var res = await fetch(API + '/game/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        save_id: currentSaveId, action: text,
        speak: speak, regret: regret, accelerate: accelerate,
        target_paragraph_index: regret ? paragraphIndex : null
      }),
      signal: _streamAbort.signal
    });

    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var buf = '';

    while (true) {
      var done_result = await reader.read();
      if (done_result.done) break;
      buf += decoder.decode(done_result.value, { stream: true });

      var lines = buf.split('\n');
      buf = lines.pop();
      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        if (line.startsWith('data: ')) {
          try {
            var event = JSON.parse(line.slice(6));
            if (isFirstStart && !_firstStartEntered) {
              _firstStartEntered = true;
              if (startBtn) stopGenTimer(startBtn, '开始新剧本');
              closeBookModal();
              paragraphQueue = [{ type: 'narration', text: '…' }];
              paragraphIndex = 0;
              enterGameStage(bookTitle);
            }
            handleStreamEvent(event);
          } catch(e) {}
        }
      }
    }

    if (buf) {
      var remLines = buf.split('\n');
      for (var j = 0; j < remLines.length; j++) {
        var rl = remLines[j];
        if (rl.startsWith('data: ')) {
          try {
            var ev = JSON.parse(rl.slice(6));
            if (isFirstStart && !_firstStartEntered) {
              _firstStartEntered = true;
              if (startBtn) stopGenTimer(startBtn, '开始新剧本');
              closeBookModal();
              paragraphQueue = [{ type: 'narration', text: '…' }];
              paragraphIndex = 0;
              enterGameStage(bookTitle);
            }
            handleStreamEvent(ev);
          } catch(e) {}
        }
      }
    }
  } catch(e) {
    if (e.name !== 'AbortError') {
      showToast('Stream 错误：' + e.message, 'error');
    }
  }

  if (!isFirstStart) { stopGenTimer(btn, origText); }
  _submitting = false;
  _streamAbort = null;

  if (_streamingQueue.length > 0) {
    paragraphQueue = _streamingQueue.slice();
    paragraphIndex = _streamingCurrentIdx;
    _streamingQueue = [];
    _streamingDone = true;
    removeArrow();
    if (paragraphIndex >= paragraphQueue.length - 1) {
      setActionInputDisabled(false);
    }
    renderParagraph();
  } else {
    setActionInputDisabled(false);
    _streamingQueue = [];
    _streamingDone = true;
  }
  reloadMemoAndRefs();
}

function handleStreamEvent(event) {
  if (event.type === 'partial') {
    if (_streamingQueue.length === 0 || _streamingQueue[_streamingQueue.length - 1]._done) {
      _streamingQueue.push({ type: 'narration', text: '', _done: false });
    }
    var cur = _streamingQueue[_streamingQueue.length - 1];
    cur.text += event.text;
    if (_streamingCurrentIdx === _streamingQueue.length - 1) {
      renderParagraphStreaming();
    }
  } else if (event.type === 'paragraph') {
    if (_streamingQueue.length > 0 && !_streamingQueue[_streamingQueue.length - 1]._done) {
      var last = _streamingQueue[_streamingQueue.length - 1];
      last.type = event.para.type;
      last.text = event.para.text;
      if (event.para.speaker) last.speaker = event.para.speaker;
      last._done = true;
    } else {
      event.para._done = true;
      _streamingQueue.push(event.para);
    }
    renderParagraphStreaming();
  } else if (event.type === 'done') {
    if (_streamingQueue.length > 0 && !_streamingQueue[_streamingQueue.length - 1].text) {
      _streamingQueue.pop();
    }
    _streamingDone = true;
    renderParagraphStreaming();
  } else if (event.type === 'error') {
    showToast(event.message, 'error');
  }
}

function renderParagraphStreaming() {
  paragraphQueue = _streamingQueue.slice();
  if (paragraphQueue.length === 0) return;

  if (_streamingCurrentIdx >= paragraphQueue.length) {
    _streamingCurrentIdx = paragraphQueue.length - 1;
  }
  var p = paragraphQueue[_streamingCurrentIdx];
  if (!p) return;

  if (p.type === 'dialogue') {
    document.getElementById('dialog-speaker').textContent = p.speaker || '';
  } else {
    document.getElementById('dialog-speaker').textContent = '';
  }
  document.getElementById('dialog-text').textContent = p.text || '';

  // Add to storyHistory by index to avoid duplicates
  if (p._done && _streamingCurrentIdx > _lastHistoryIdx) {
    var cleanPara = { type: p.type, text: p.text };
    if (p.speaker) cleanPara.speaker = p.speaker;
    storyHistory.push(cleanPara);
    _lastHistoryIdx = _streamingCurrentIdx;
  }

  var hasMoreAhead = (_streamingCurrentIdx < paragraphQueue.length - 1);
  var isLastAndWaiting = (!_streamingDone && !hasMoreAhead && paragraphQueue.length > 0);

  if (hasMoreAhead || isLastAndWaiting) {
    setArrowVisible(true);
  } else if (_streamingDone) {
    setArrowVisible(false);
    setActionInputDisabled(false);
  }
}

function advanceStreamParagraph() {
  if (_streamingCurrentIdx < paragraphQueue.length - 1) {
    _streamingCurrentIdx++;
    renderParagraphStreaming();
  } else if (_streamingDone) {
    setActionInputDisabled(false);
    setArrowVisible(false);
    renderParagraph();
  }
}

advanceParagraph = function() {
  if (!_streamingDone && (_streamAbort || _streamingQueue.length > 0)) {
    if (_streamingCurrentIdx >= paragraphQueue.length - 1) return;
    advanceStreamParagraph();
    return;
  }
  if (isAutoPlaying) return;
  if (paragraphIndex >= paragraphQueue.length) return;
  paragraphIndex++;
  renderParagraph();
};

