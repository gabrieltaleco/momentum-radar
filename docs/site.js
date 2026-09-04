const loginView = document.getElementById('login-view');
const radarView = document.getElementById('radar-view');
const loginForm = document.getElementById('login-form');
const loginMessage = document.getElementById('login-message');
const SESSION_KEY = 'radar-authenticated-v2';
// Altera o utilizador e gera um novo SHA-256 para outra palavra-passe.
const ACCESS = Object.freeze({ username: 'admin', passwordHash: 'f226a9d29cdb97d342436fe240a05ca06bb3cb037025874347b5ae06f1bf963b' });
let state = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

async function hashPassword(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function showRadar() {
  loginView.hidden = true;
  radarView.hidden = false;
  if (state) render();
}

function showLogin() {
  radarView.hidden = true;
  loginView.hidden = false;
  loginForm.password.value = '';
  loginForm.username.focus();
}

function actionClass(action) {
  const text = String(action || '').toLowerCase();
  if (text.includes('compra')) return 'buy';
  if (text.includes('reduzir') || text.includes('evitar') || text.includes('vender')) return 'sell';
  return 'hold';
}

function render() {
  const meta = state.meta || {};
  const signals = Array.isArray(state.signals) ? state.signals : [];
  document.getElementById('hero-copy').textContent = `Snapshot de ${meta.as_of || 'data desconhecida'} com ${signals.length} leituras. Usa-o como ponto de partida e confirma os dados antes de decidir.`;
  document.getElementById('macro-score').textContent = Number(meta.macro_score || 0).toFixed(1);
  document.getElementById('snapshot-date').textContent = `Gerado em ${meta.as_of || 'snapshot'} · ${meta.mode || 'demo'}`;
  document.getElementById('asset-count').textContent = signals.length;
  const average = signals.length ? signals.reduce((sum, item) => sum + Number(item.score || 0), 0) / signals.length : 0;
  document.getElementById('average-score').textContent = average.toFixed(1);
  const best = [...signals].sort((a, b) => Number(b.score || 0) - Number(a.score || 0))[0];
  document.getElementById('top-asset').textContent = best ? `${best.symbol} · ${Number(best.score).toFixed(1)}` : 'Sem dados';
  const sectors = [...new Set(signals.map((item) => item.sector).filter(Boolean))].sort();
  document.getElementById('sector').innerHTML = '<option>Todos</option>' + sectors.map((item) => `<option>${escapeHtml(item)}</option>`).join('');
  renderAssets();
}

function renderAssets() {
  const query = document.getElementById('search').value.trim().toLowerCase();
  const sector = document.getElementById('sector').value;
  const signals = (state.signals || []).filter((item) => (!query || `${item.symbol} ${item.sector}`.toLowerCase().includes(query)) && (sector === 'Todos' || item.sector === sector));
  const grid = document.getElementById('asset-grid');
  if (!signals.length) { grid.innerHTML = '<p class="empty">Não existem ativos com estes filtros.</p>'; return; }
  grid.innerHTML = signals.map((item) => {
    const score = Math.max(0, Math.min(100, Number(item.score || 0)));
    return `<article class="asset-card"><h3>${escapeHtml(item.symbol)}</h3><p class="asset-sector">${escapeHtml(item.sector || 'Setor não indicado')}</p><div class="asset-meta"><div><span>score</span><strong>${score.toFixed(1)}</strong></div><div><span>confiança</span><strong>${Number(item.confidence || 0).toFixed(1)}%</strong></div></div><div class="score-bar" aria-label="Score ${score.toFixed(1)} de 100"><span style="width:${score}%"></span></div><span class="action ${actionClass(item.action)}">${escapeHtml(item.action || 'Observar')}</span><p class="asset-note">${escapeHtml(item.notes || 'Confirma tendência, risco e horizonte antes de agir.')}</p></article>`;
  }).join('');
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const username = loginForm.username.value.trim();
  const password = loginForm.password.value;
  if (!username || !password) { loginMessage.textContent = 'Preenche os dois campos para entrar.'; loginMessage.className = 'message error'; return; }
  let passwordHash = '';
  try { passwordHash = await hashPassword(password); } catch (error) {
    loginMessage.textContent = 'Não foi possível validar a palavra-passe neste navegador.';
    loginMessage.className = 'message error';
    return;
  }
  if (username !== ACCESS.username || passwordHash !== ACCESS.passwordHash) {
    loginMessage.textContent = 'Utilizador ou palavra-passe incorretos.';
    loginMessage.className = 'message error';
    loginForm.password.value = '';
    loginForm.password.focus();
    return;
  }
  sessionStorage.setItem(SESSION_KEY, '1');
  loginMessage.textContent = '';
  loginMessage.className = 'message';
  showRadar();
});
document.getElementById('logout-button').addEventListener('click', () => { sessionStorage.removeItem(SESSION_KEY); showLogin(); });
document.getElementById('search').addEventListener('input', renderAssets);
document.getElementById('sector').addEventListener('change', renderAssets);
document.getElementById('clear-filters').addEventListener('click', () => { document.getElementById('search').value = ''; document.getElementById('sector').value = 'Todos'; renderAssets(); });

fetch('./demo-data.json').then((response) => { if (!response.ok) throw new Error('snapshot unavailable'); return response.json(); }).then((payload) => { state = payload; if (sessionStorage.getItem(SESSION_KEY) === '1') showRadar(); }).catch(() => { loginMessage.textContent = 'Não foi possível carregar o snapshot de demonstração.'; loginMessage.className = 'message error'; });
