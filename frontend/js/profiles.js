// ── PROFILE MANAGEMENT ──
var currentActiveProfile = '';

function showProfileSidebar() {
  document.getElementById('profile-sidebar').classList.add('active');
  loadProfileList();
}

function hideProfileSidebar() {
  document.getElementById('profile-sidebar').classList.remove('active');
}

async function loadProfileList() {
  try {
    var res = await fetch(API + '/profiles');
    var data = await res.json();
    currentActiveProfile = data.active_profile;
    var list = document.getElementById('profile-list');
    list.innerHTML = data.profiles.map(function(name) {
      var isActive = name === currentActiveProfile;
      var cls = 'profile-item' + (isActive ? ' active' : '');
      var delBtn = data.profiles.length > 1
        ? '<button class="del-btn" onclick="event.stopPropagation();deleteProfile(\'' + escHtml(name) + '\')">×</button>'
        : '';
      return '<div class="' + cls + '" onclick="switchProfile(\'' + escHtml(name) + '\')">' + escHtml(name) + delBtn + '</div>';
    }).join('');
  } catch(e) {
    showToast('加载 Profiles 失败', 'error');
  }
}

async function switchProfile(name) {
  try {
    var res = await fetch(API + '/profiles/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    var data = await res.json();
    currentActiveProfile = data.active_profile;
    // Reload settings display with new profile's data
    populateSettingsForm(data.settings);
    loadProfileList();
    showToast('已切换到 ' + name, 'success');
  } catch(e) {
    showToast('切换失败：' + e.message, 'error');
  }
}

async function createProfile() {
  var input = document.getElementById('new-profile-name');
  var name = input.value.trim();
  if (!name) return;
  try {
    var res = await fetch(API + '/profiles/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    if (!res.ok) {
      var err = await res.json();
      showToast(err.detail || '创建失败', 'error');
      return;
    }
    var data = await res.json();
    currentActiveProfile = data.active_profile;
    populateSettingsForm(data.settings);
    loadProfileList();
    input.value = '';
    showToast('已创建 ' + name, 'success');
  } catch(e) {
    showToast('创建失败：' + e.message, 'error');
  }
}

async function deleteProfile(name) {
  var confirmed = await showConfirm('删除 Profile', '确定要删除 "' + name + '" 吗？', '删除');
  if (!confirmed) return;
  try {
    var res = await fetch(API + '/profiles/' + encodeURIComponent(name), { method: 'DELETE' });
    if (!res.ok) {
      var err = await res.json();
      showToast(err.detail || '删除失败', 'error');
      return;
    }
    var data = await res.json();
    currentActiveProfile = data.active_profile;
    loadProfileList();
    // Reload active profile's settings
    var sRes = await fetch(API + '/settings');
    var sData = await sRes.json();
    populateSettingsForm(sData);
    showToast('已删除', 'success');
  } catch(e) {
    showToast('删除失败：' + e.message, 'error');
  }
}

// Helper: populate settings form fields from a settings object
function populateSettingsForm(s) {
  document.getElementById('cfg-llm-url').value = s.llm_base_url || '';
  document.getElementById('cfg-llm-key').value = s.llm_api_key || '';
  document.getElementById('cfg-llm-model').value = s.llm_model || '';
  document.getElementById('cfg-img-url').value = s.image_base_url || '';
  document.getElementById('cfg-img-key').value = s.image_api_key || '';
  document.getElementById('cfg-img-model').value = s.image_model || '';
  document.getElementById('cfg-tts').value = s.tts_endpoint || '';
  document.getElementById('cfg-llm-timeout').value = s.llm_timeout != null ? s.llm_timeout : 60;
  document.getElementById('cfg-llm-debug').checked = s.llm_debug === true;
  document.getElementById('cfg-llm-extra-body').value = s.llm_extra_body || '';
  document.getElementById('cfg-streaming').checked = s.streaming !== false;
  document.getElementById('cfg-comprehension').checked = s.comprehension !== false;
}


