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
  if (view === 'settings') { loadSettings(); } else { hideProfileSidebar(); }
}

