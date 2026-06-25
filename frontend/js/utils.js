// ── HELPERS ──
function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── TIMER ──
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
