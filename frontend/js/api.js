// ── API TEST ──
async function testApi(type) {
  var url, key, model;
  if (type === 'llm') {
    url = document.getElementById('cfg-llm-url').value;
    key = document.getElementById('cfg-llm-key').value;
    model = document.getElementById('cfg-llm-model').value;
  } else if (type === 'image') {
    url = document.getElementById('cfg-img-url').value;
    key = document.getElementById('cfg-img-key').value;
    model = document.getElementById('cfg-img-model').value;
  } else if (type === 'tts') {
    url = document.getElementById('cfg-tts').value;
  }

  if (!url) { showToast('请先输入 Base URL', 'error'); return; }
  if (type !== 'tts' && !key) { showToast('请先输入 API Key', 'error'); return; }

  var btn = document.getElementById('btn-test-' + type);
  var origText = btn.textContent;
  btn.textContent = '测试中…';
  btn.disabled = true;

  try {
    var apiUrl = url.replace(/\/+$/, '');
    var resp;
    if (type === 'tts') {
      resp = await fetch(apiUrl, { method: 'GET', signal: AbortSignal.timeout(5000) });
    } else {
      resp = await fetch(apiUrl + '/models', {
        headers: { 'Authorization': 'Bearer ' + key },
        signal: AbortSignal.timeout(8000)
      });
    }
    if (resp.ok) {
      showToast(type.toUpperCase() + ' API 连接成功！', 'success');
    } else {
      var txt = '';
      try { txt = await resp.text(); } catch(e) {}
      showToast(type.toUpperCase() + ' API 错误：' + resp.status + ' ' + txt.slice(0, 60), 'error');
    }
  } catch(e) {
    showToast(type.toUpperCase() + ' API 无法访问：' + e.message, 'error');
  }
  btn.textContent = origText;
  btn.disabled = false;
}

// ── API HEALTH CHECK ──
async function checkApiHealth() {
  try {
    var resp = await fetch(API + '/books', { signal: AbortSignal.timeout(5000) });
    if (resp.ok) return true;
    showToast('后端 API 错误：' + resp.status, 'error');
    return false;
  } catch(e) {
    showToast('后端 API 无法访问，请先启动服务器', 'error');
    return false;
  }
}

// ── LLM API HEALTH CHECK ──
async function checkLlmHealth() {
  try {
    var resp = await fetch(API + '/settings');
    var s = await resp.json();
    var key = s.llm_api_key || '';
    if (!key || key === 'sk-placeholder') return true;
    var url = (s.llm_base_url || 'https://api.openai.com/v1').replace(/\/+$/, '');
    var testResp = await fetch(url + '/models', {
      headers: { 'Authorization': 'Bearer ' + key },
      signal: AbortSignal.timeout(8000)
    });
    if (testResp.ok) return true;
    showToast('大模型 API 错误：' + testResp.status + '，请检查 API 设置', 'error');
    return false;
  } catch(e) {
    showToast('大模型 API 无法访问：' + e.message + '，请检查 API 设置', 'error');
    return false;
  }
}
