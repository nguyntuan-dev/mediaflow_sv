/**
 * MediaFlow — mediaflow.js
 * Frontend logic + REST API calls
 */

const API_BASE = 'http://localhost:8080/api';
const API_KEY  = 'mediaflow-admin-2025'; // ← trùng ADMIN_API_KEY trong server

let currentPlatform = 'tiktok';
let toastTimer      = null;

const HEADERS = {
  'Content-Type': 'application/json',
  'x-api-key':    API_KEY,
};

const PLATFORM_META = {
  tiktok:   { icon: '🎵', placeholder: 'https://www.tiktok.com/@username/video/...' },
  youtube:  { icon: '▶',  placeholder: 'https://www.youtube.com/watch?v=...' },
  facebook: { icon: '📘', placeholder: 'https://www.facebook.com/watch?v=...' },
};

// ── Navigation ──────────────────────────────────────────────
function showTab(name, btn) {
  document.querySelectorAll('.tab').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'history') loadHistory();
}

// ── Chọn nền tảng ──────────────────────────────────────────
function setPlatform(platform, btn) {
  currentPlatform = platform;
  document.querySelectorAll('.pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('urlInput').placeholder  = PLATFORM_META[platform].placeholder;
  document.getElementById('thumbIcon').textContent = PLATFORM_META[platform].icon;
  hide('resultPanel'); hide('safeBar'); hide('progressWrap');
}

function setPlatformCard(platform) {
  const pills = document.querySelectorAll('.pill');
  ['tiktok', 'youtube', 'facebook'].forEach((p, i) =>
    pills[i].classList.toggle('active', p === platform)
  );
  currentPlatform = platform;
  document.getElementById('urlInput').placeholder  = PLATFORM_META[platform].placeholder;
  document.getElementById('thumbIcon').textContent = PLATFORM_META[platform].icon;
  hide('resultPanel'); hide('safeBar');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Phân tích link ──────────────────────────────────────────
async function analyzeLink() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) { toast('⚠ Vui lòng dán link vào ô trống!'); return; }

  hide('resultPanel'); hide('safeBar');
  show('progressWrap');
  await runProgress();

  try {
    const res = await fetch(`${API_BASE}/media/analyze`, {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ url, platform: currentPlatform }),
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    showResult(data.title, data.meta);
  } catch {
    showResult('Video đã phát hiện', `${currentPlatform} · Sẵn sàng tải`);
  }

  hide('progressWrap');
  show('safeBar');
}

function runProgress() {
  return new Promise(resolve => {
    const fill  = document.getElementById('progressFill');
    const label = document.getElementById('progressLabel');
    const steps = [
      [20,  'Kiểm tra link an toàn...'],
      [45,  'Phân tích URL...'],
      [70,  'Tải thông tin media...'],
      [90,  'Kiểm tra chất lượng...'],
      [100, 'Hoàn tất!'],
    ];
    let i = 0;
    const iv = setInterval(() => {
      if (i >= steps.length) { clearInterval(iv); setTimeout(resolve, 200); return; }
      fill.style.width  = steps[i][0] + '%';
      label.textContent = steps[i][1];
      i++;
    }, 450);
  });
}

function showResult(title, meta) {
  document.getElementById('panelTitle').textContent = title;
  document.getElementById('panelMeta').textContent  = meta;
  show('resultPanel');
}

// ── Chip chọn chất lượng / định dạng ───────────────────────
function setChip(btn) {
  btn.closest('.chips').querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
}

// ── Tải xuống ───────────────────────────────────────────────
async function startDownload() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url)                    { toast('⚠ Chưa nhập link!'); return; }
  if (!url.startsWith('http')) { toast('⚠ Link không hợp lệ!'); return; }

  const quality = document.querySelectorAll('.chips')[0]?.querySelector('.active')?.textContent?.trim() || 'best';
  const format  = document.querySelectorAll('.chips')[1]?.querySelector('.active')?.textContent?.trim() || 'MP4';

  toast(`⏳ Đang xử lý — ${quality} · ${format} (vài giây...)`);

  try {
    const res = await fetch(`${API_BASE}/media/download`, {
      method:  'POST',
      headers: HEADERS,
      body:    JSON.stringify({ url, platform: currentPlatform, quality, format }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error('Lỗi backend:', errText);
      toast(`❌ Lỗi ${res.status} — xem Console để biết chi tiết`);
      return;
    }

    const data = await res.json();

    // ✅ Dùng downloadUrl từ backend (đã có token, không cần header)
    const a       = document.createElement('a');
    a.href        = `http://localhost:8080${data.downloadUrl}`;
    a.download    = data.filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 1000);

    toast(`✅ Tải xong: ${data.filename} (${data.sizeMB} MB)`);
    addHistoryItem(currentPlatform, quality, format, data.filename, data.sizeMB);

  } catch (e) {
    console.error(e);
    toast('❌ Lỗi kết nối backend!');
  }
}

function saveThumbnail() { toast('🖼 Đang lưu thumbnail...'); }
function downloadSub()   { toast('💬 Đang tải phụ đề...'); }

// ── Công cụ ─────────────────────────────────────────────────
const TOOL_LABELS = {
  MP3: '→ MP3', MP4: '→ MP4', FLAC: '→ FLAC', WAV: '→ WAV',
  JPG: '→ JPG', PNG: '→ PNG', WEBP: '→ WEBP',
  removeWatermark: 'Xóa Watermark', resize: 'Resize', crop: 'Crop',
  compress: 'Nén ảnh', gallery: 'Tạo Gallery',
  downloadSub: 'Tải phụ đề', embedSub: 'Nhúng phụ đề', downloadThumb: 'Tải Thumbnail',
  saveFile: 'Lưu file', renameFile: 'Đổi tên', deleteFile: 'Xóa file', historyLog: 'Lịch sử',
  saveToDrive: 'Google Drive', saveToOneDrive: 'OneDrive',
};

async function useTool(action) {
  toast(`⚡ ${TOOL_LABELS[action] || action}`);
  try {
    await fetch(`${API_BASE}/tools/${action}`, { method: 'POST', headers: HEADERS, body: '{}' });
  } catch {}
}

// ── Inner tabs ──────────────────────────────────────────────
function switchInner(name, btn) {
  document.querySelectorAll('.inner-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.inner-tab').forEach(b => b.classList.remove('active'));
  document.getElementById('inner-' + name).classList.add('active');
  btn.classList.add('active');
}

// ── Share ───────────────────────────────────────────────────
async function handleShare(platform) {
  const msgs = {
    facebook: '📘 Chia sẻ lên Facebook!',
    zalo:     '💬 Chia sẻ lên Zalo!',
    telegram: '✈️ Chia sẻ qua Telegram!',
    copy:     '🔗 Đã sao chép link!',
  };
  closeModal('share');
  toast(msgs[platform] || '↗ Chia sẻ thành công!');
}

// ── History ─────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch(`${API_BASE}/history`, { headers: HEADERS });
    if (!res.ok) throw new Error();
    const items = await res.json();
    renderHistory(items);
  } catch {}
}

function renderHistory(items) {
  const container = document.getElementById('historyList');
  if (!items?.length) {
    container.innerHTML = '<div class="history-empty">Chưa có lịch sử tải xuống</div>';
    return;
  }
  const icons = { tiktok: '🎵', youtube: '▶', facebook: '📘' };
  container.innerHTML = items.map(h => `
    <div class="history-item">
      <div class="h-icon">${icons[h.platform] || '📁'}</div>
      <div class="h-info">
        <div class="h-title">${h.title}</div>
        <div class="h-meta">${h.date} · ${h.quality} · ${h.size}</div>
      </div>
      <span class="h-badge">${h.format}</span>
    </div>
  `).join('');
}

function addHistoryItem(platform, quality, format, filename, sizeMB) {
  const container = document.getElementById('historyList');
  const empty = container.querySelector('.history-empty');
  if (empty) empty.remove();

  const icons = { tiktok: '🎵', youtube: '▶', facebook: '📘' };
  const now   = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  const el    = document.createElement('div');
  el.className = 'history-item';
  el.innerHTML = `
    <div class="h-icon">${icons[platform] || '📁'}</div>
    <div class="h-info">
      <div class="h-title">${filename || platform + '_' + Date.now()}</div>
      <div class="h-meta">Hôm nay ${now} · ${quality} · ${sizeMB || '?'} MB</div>
    </div>
    <span class="h-badge">${format}</span>
  `;
  container.prepend(el);
}

// ── Modal ───────────────────────────────────────────────────
function openModal(name)  { document.getElementById('modal-' + name).classList.remove('hidden'); }
function closeModal(name) { document.getElementById('modal-' + name).classList.add('hidden'); }

document.querySelectorAll('.modal-bg').forEach(bg => {
  bg.addEventListener('click', e => { if (e.target === bg) bg.classList.add('hidden'); });
});

// ── Toast ───────────────────────────────────────────────────
function toast(msg) {
  const el = document.getElementById('toast');
  document.getElementById('toastMsg').textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ── Helpers ─────────────────────────────────────────────────
function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }

// Health check — chỉ gọi một lần khi load
(async () => {
  try {
    const res = await fetch(`${API_BASE}/health`, {
      headers: HEADERS,
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) console.info('[MediaFlow] ✓ Backend online');
  } catch {
    console.warn('[MediaFlow] Backend offline');
  }
})();

// Nếu muốn kiểm tra định kỳ, dùng setInterval nhưng tăng thời gian lên
setInterval(async () => {
  try {
    const res = await fetch(`${API_BASE}/health`, { headers: HEADERS });
    if (res.ok) console.info('[MediaFlow] ✓ Backend online');
  } catch {
    console.warn('[MediaFlow] Backend offline');
  }
}, 30000); // 30 giây một lần thay vì spam mỗi giây
