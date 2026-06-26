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
  var text = storyHistory.map(function(p) { return p.text; }).join('\n\n');
  var blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url; a.download = 'storydive_export.txt';
  a.click(); URL.revokeObjectURL(url);
}
