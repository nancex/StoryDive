// ── SETTINGS ──
async function loadSettings() {
  try {
    var res = await fetch(API + '/settings');
    var s = await res.json();
    populateSettingsForm(s);
    // Only show profile sidebar if settings view is active
    var settingsView = document.getElementById('view-settings');
    if (settingsView && settingsView.classList.contains('active')) {
      loadProfileList();
      showProfileSidebar();
    }
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
    llm_timeout: parseInt(document.getElementById('cfg-llm-timeout').value) || 60,
    llm_extra_body: document.getElementById('cfg-llm-extra-body').value
  };
  await fetch(API + '/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
  showToast('设置已保存', 'success');
}



