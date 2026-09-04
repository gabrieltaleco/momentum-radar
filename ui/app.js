function loadFavorites() {
  try {
    const value = JSON.parse(localStorage.getItem('radar:favorites') || '[]');
    return new Set(Array.isArray(value) ? value.map((item) => String(item).toUpperCase()) : []);
  } catch (_error) {
    return new Set();
  }
}

function loadSavedViews() {
  try {
    const value = JSON.parse(localStorage.getItem('radar:saved-views') || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item) => item && typeof item.name === 'string').slice(0, 12).map((item) => ({
      name: item.name.slice(0, 32),
      query: String(item.query || '').slice(0, 80),
      sector: String(item.sector || 'Todos'),
      quickFilter: String(item.quickFilter || 'all'),
      sort: ['score', 'symbol', 'sector', 'action', 'favorite'].includes(item.sort) ? item.sort : 'score',
    }));
  } catch (_error) {
    return [];
  }
}

function loadReviewedAlerts() {
  try {
    const value = JSON.parse(localStorage.getItem('radar:reviewed-alerts') || '[]');
    return new Set(Array.isArray(value) ? value.map((item) => String(item)).slice(0, 300) : []);
  } catch (_error) {
    return new Set();
  }
}

function loadWatchRules() {
  try {
    const value = JSON.parse(localStorage.getItem('radar:watch-rules') || '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((item) => item && ['score', 'confidence', 'momentum', 'relative_strength'].includes(item.metric) && ['gte', 'lte'].includes(item.operator) && ['all', 'favorites', 'portfolio', 'sector'].includes(item.scope) && Number.isFinite(Number(item.threshold))).slice(0, 20).map((item) => ({
      id: String(item.id || `${Date.now()}-${Math.random()}`).slice(0, 50),
      metric: item.metric,
      operator: item.operator,
      threshold: Number(item.threshold),
      scope: item.scope,
      trigger: item.trigger === 'always' ? 'always' : 'enter',
    }));
  } catch (_error) {
    return [];
  }
}

function loadWatchRuleMatches() {
  try {
    const value = JSON.parse(localStorage.getItem('radar:watch-rule-matches') || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch (_error) {
    return {};
  }
}

function loadNotificationPreference() {
  try {
    return localStorage.getItem('radar:local-notifications') === 'on';
  } catch (_error) {
    return false;
  }
}

const ui = {
  state: null,
  selected: null,
  sector: 'Todos',
  query: '',
  quickFilter: 'all',
  favorites: loadFavorites(),
  savedViews: loadSavedViews(),
  lastUsage: null,
  alertFilter: 'all',
  alertQuery: '',
  alertSort: 'priority',
  alertItems: [],
  reviewedAlerts: loadReviewedAlerts(),
  watchRules: loadWatchRules(),
  watchRuleMatches: loadWatchRuleMatches(),
  notificationsEnabled: loadNotificationPreference(),
  compareSymbols: [],
  assetSort: 'score',
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function money(value, currency = 'USD') {
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount === 0) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: amount < 10 ? 4 : 2 }).format(amount);
}

function percent(value, digits = 1) {
  const amount = Number(value);
  return Number.isFinite(amount) ? `${(amount * 100).toFixed(digits)}%` : '—';
}

function score(value) {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount.toFixed(1) : '—';
}

function metricReading(metric, rawValue) {
  const value = Number(rawValue);
  if (!Number.isFinite(value)) return { level: 'Sem dados', band: '—', meaning: 'Não há valor suficiente para interpretar.' };
  const generic = (level, band, meaning) => ({ level, band, meaning });
  if (metric === 'drawdown') {
    const pct = Math.abs(value) <= 1 ? value * 100 : value;
    if (pct < 5) return generic('Pequeno', '0-4,9%', 'Está perto do pico recente.');
    if (pct < 15) return generic('Moderado', '5-14,9%', 'Caiu de forma visível desde o pico.');
    if (pct < 30) return generic('Elevado', '15-29,9%', 'Está bastante abaixo do pico recente.');
    return generic('Muito elevado', '30% ou mais', 'A queda desde o pico é profunda.');
  }
  if (metric === 'risk_penalty') {
    if (value < 5) return generic('Baixo', '0-4,9', 'Pouca penalização por instabilidade ou queda.');
    if (value < 12) return generic('Moderado', '5-11,9', 'Há alguma instabilidade a vigiar.');
    if (value < 20) return generic('Elevado', '12-19,9', 'A volatilidade ou queda já pesa na decisão.');
    return generic('Muito elevado', '20-30', 'O ativo esteve instável ou caiu bastante.');
  }
  if (metric === 'confidence') {
    if (value < 50) return generic('Baixa', '0-49', 'Os fatores discordam ou há pouco histórico.');
    if (value < 70) return generic('Média', '50-69', 'Há algum apoio, mas ainda existem dúvidas.');
    if (value < 85) return generic('Boa', '70-84', 'Os fatores são relativamente consistentes.');
    return generic('Alta', '85-100', 'Os fatores e o histórico estão bastante alinhados.');
  }
  if (metric === 'relative_strength') {
    if (value < 40) return generic('Abaixo do mercado', '0-39', 'Está a ficar para trás do mercado de comparação.');
    if (value < 60) return generic('Parecido com o mercado', '40-59', 'Acompanha o mercado de comparação sem vantagem clara.');
    if (value < 80) return generic('Acima do mercado', '60-79', 'Está a superar o mercado de comparação.');
    return generic('Muito acima do mercado', '80-100', 'Está a superar claramente o mercado de comparação.');
  }
  if (value < 40) return generic('Fraco', '0-39', metric === 'momentum' ? 'O preço perdeu impulso.' : 'Pouco apoio neste fator.');
  if (value < 60) return generic('Moderado / neutro', '40-59', metric === 'momentum' ? 'O preço não mostra impulso claro.' : 'Sinais mistos; não há confirmação clara.');
  if (value < 80) return generic('Favorável', '60-79', 'Este fator ajuda a leitura do ativo.');
  return generic('Muito forte', '80-100', 'Este fator está claramente positivo.');
}

function personalizedMetricReading(metric, rawValue, asset, signal) {
  const reading = metricReading(metric, rawValue);
  const name = asset?.name || asset?.symbol || 'este ativo';
  const sector = String(asset?.sector || 'este tipo de ativo').toLowerCase();
  const momentum = Number(signal?.momentum ?? 50);
  const trend = Number(signal?.trend ?? 50);
  const value = Number(rawValue);
  let personalized = reading.meaning;
  if (metric === 'momentum') {
    personalized = value < 40 ? `O preço de ${name} perdeu força recentemente.` : value < 60 ? `O preço de ${name} não mostra um impulso claro.` : value < 80 ? `O preço de ${name} ganhou força recente; confirma a direção e o risco.` : `${name} tem impulso muito forte; pode ser tendência ou entusiasmo excessivo.`;
  } else if (metric === 'relative_strength') {
    personalized = value < 40 ? `${name} está a render menos do que o mercado usado para comparação.` : value < 60 ? `${name} acompanha o mercado sem vantagem clara.` : `${name} está a comportar-se melhor do que o mercado de comparação.`;
  } else if (metric === 'trend') {
    personalized = value < 40 ? `A direção recente de ${name} é fraca ou descendente.` : value < 60 ? `A direção de ${name} está indecisa.` : `A direção de ${name} é positiva em várias janelas.`;
  } else if (metric === 'breadth') {
    personalized = `Mede se as partes que representam ${name} ou o seu tema confirmam o movimento. ${reading.meaning}`;
  } else if (metric === 'volume') {
    personalized = value < 40 ? `${name} teve pouca atividade face ao seu padrão recente.` : value < 60 ? `A atividade de ${name} está perto do normal.` : value < 80 ? `A atividade de ${name} está acima do normal; o volume sozinho não diz se predominam compras ou vendas.` : `${name} está a negociar muito acima do normal. Com impulso ${Number.isFinite(momentum) ? momentum.toFixed(1) : '—'} e direção ${Number.isFinite(trend) ? trend.toFixed(1) : '—'}, pode haver interesse e vendas nervosas; não chamamos isto de panic sell sem dados adicionais.`;
  } else if (metric === 'news') {
    personalized = value >= 60 ? `As notícias associadas a ${name} ajudam a narrativa, mas podem trazer hype.` : value < 40 ? `As notícias associadas a ${name} estão a pesar contra o ativo.` : `As notícias associadas a ${name} estão neutras ou pouco decisivas.`;
  } else if (metric === 'macro') {
    personalized = `O ambiente económico atual é ${reading.level.toLowerCase()} para ${name} e ativos de ${sector}.`;
  }
  return { ...reading, personalized };
}

function actionClass(action) {
  const value = String(action || '').toLowerCase();
  if (value.includes('compra')) return 'action-buy';
  if (value.includes('reduzir') || value.includes('evitar') || value.includes('vender')) return 'action-sell';
  if (value.includes('manter')) return 'action-hold';
  return 'action-none';
}

function actionShort(action) {
  const value = String(action || 'Sem análise');
  if (value.includes('Considerar compra')) return 'Compra?';
  if (value.includes('Manter')) return 'Manter';
  if (value.includes('Reduzir')) return 'Reduzir';
  if (value.includes('Não agir')) return 'Aguardar';
  return value;
}

function dateLabel(value) {
  if (!value) return 'sem data';
  const parsed = new Date(`${value}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('pt-PT', { day: '2-digit', month: 'short', year: 'numeric' });
}

function signalMap() {
  return new Map((ui.state?.signals || []).map((item) => [String(item.symbol).toUpperCase(), item]));
}

function favorite(symbol) {
  return ui.favorites.has(String(symbol).toUpperCase());
}

function toggleFavorite(symbol) {
  const wanted = String(symbol).toUpperCase();
  if (favorite(wanted)) ui.favorites.delete(wanted);
  else ui.favorites.add(wanted);
  localStorage.setItem('radar:favorites', JSON.stringify([...ui.favorites].sort()));
  renderFilters();
  renderAssets();
}

function toggleCompare(symbol) {
  const wanted = String(symbol).toUpperCase();
  const existing = ui.compareSymbols.indexOf(wanted);
  if (existing >= 0) {
    ui.compareSymbols.splice(existing, 1);
  } else if (ui.compareSymbols.length >= 3) {
    const message = $('#compare-message');
    if (message) message.textContent = 'Compara até três ativos de cada vez.';
    return;
  } else {
    ui.compareSymbols.push(wanted);
  }
  renderAssets();
}

function qualityMap() {
  return new Map((ui.state?.quality || []).map((item) => [String(item.symbol).toUpperCase(), item]));
}

function journalFor(symbol, asOf) {
  return (ui.state?.journal || []).find((item) => String(item.symbol).toUpperCase() === String(symbol).toUpperCase() && String(item.as_of) === String(asOf));
}

function renderSummary() {
  const state = ui.state;
  const signals = state.signals || [];
  const buy = signals.filter((item) => String(item.action).toLowerCase().includes('compra'));
  const top = [...signals].sort((a, b) => Number(b.score || 0) - Number(a.score || 0))[0];
  const macro = Number(state.meta?.macro_score);
  const supervision = state.supervision || [];
  $('#ticker-date').textContent = dateLabel(state.meta?.as_of);
  $('#hero-action').textContent = buy.length ? 'sinais ativos' : 'sem compra clara';
  $('#hero-count').textContent = `${buy.length}/${signals.length}`;
  $('#hero-context').textContent = state.meta?.context_available === false ? 'contexto incompleto' : `ambiente económico ${score(macro)}/100`;
  $('#hero-confidence').textContent = top ? `máx. ${score(top.confidence)} conf.` : 'sem sinais';
  $('#top-asset').textContent = top ? String(top.symbol) : '—';
  $('#top-asset-copy').textContent = top ? `${actionShort(top.action)} · score ${score(top.score)} · ${top.sector}` : 'Sem sinal disponível.';
  $('#top-asset-button').onclick = () => top && selectAsset(String(top.symbol));
  $('#macro-score').textContent = Number.isFinite(macro) ? `${score(macro)}/100` : 'neutro';
  $('#macro-meter').style.width = `${Math.max(0, Math.min(100, macro || 0))}%`;
  $('#supervision-count').textContent = supervision.length ? `${supervision.length} ponto${supervision.length === 1 ? '' : 's'}` : 'estável';
  $('#supervision-copy').textContent = supervision.length ? supervision[0].title : 'Nenhum alerta crítico no snapshot.';
  const outboundCalls = Number(state.network_usage?.outbound_calls);
  const networkPlan = state.network_plan || {};
  const quotaAdvice = networkPlan.quota_advice?.alpha_vantage || {};
  const avoidedCalls = Number(networkPlan.cache_avoided_calls || 0) + Number(networkPlan.deduplicated_requests || 0);
  const planSuffix = avoidedCalls > 0 ? ` · ${avoidedCalls} chamada${avoidedCalls === 1 ? '' : 's'} evitada${avoidedCalls === 1 ? '' : 's'}` : '';
  const usageSuffix = Number.isFinite(outboundCalls) ? ` · última execução: ${outboundCalls} chamada${outboundCalls === 1 ? '' : 's'} externa${outboundCalls === 1 ? '' : 's'}${planSuffix}` : planSuffix;
  const quotaRows = state.quota?.providers || [];
  const limitedQuota = quotaRows.filter((item) => item.limit != null);
  if (!quotaRows.length) {
    $('#quota-summary').textContent = 'sem limite';
    $('#quota-copy').textContent = `Configura um orçamento local por provider se precisares de proteção adicional.${usageSuffix}`;
  } else if (!limitedQuota.length) {
    $('#quota-summary').textContent = `${quotaRows.reduce((total, item) => total + Number(item.used_today || 0), 0)} usados`;
    $('#quota-copy').textContent = `Providers monitorizados sem limite diário local.${usageSuffix}`;
  } else {
    const primary = [...limitedQuota].sort((left, right) => (right.used_today || 0) - (left.used_today || 0))[0];
    $('#quota-summary').textContent = `${primary.remaining}/${primary.limit}`;
    $('#quota-copy').textContent = `${primary.status === 'esgotado' ? `${primary.provider}: bloqueada até ao reset UTC.` : `${primary.provider}: chamadas restantes hoje.`}${usageSuffix}`;
  }
  if (quotaAdvice.recommendation) {
    $('#quota-copy').textContent += ` Margem segura: ${Number(quotaAdvice.safe_headroom || 0)} chamadas. ${quotaAdvice.recommendation}`;
  }
}

function renderDecisionBrief() {
  const container = $('#decision-brief');
  if (!container) return;
  const state = ui.state || {};
  const paper = state.paper || {};
  const review = paper.last_entry_review || {};
  const signals = state.signals || [];
  const buyCandidates = Array.isArray(review.buy_candidates) ? review.buy_candidates : [];
  const nearCandidates = Array.isArray(review.near_entry_candidates) ? review.near_entry_candidates : [];
  const threshold = Number(state.thresholds?.buy_score || 80);
  const status = $('#decision-brief-status');
  const title = $('#decision-brief-title');
  const copy = $('#decision-brief-text');
  const items = $('#decision-brief-items');
  container.classList.remove('brief-alert', 'brief-watch', 'brief-empty');
  if (!Object.keys(review).length) {
    container.classList.add('brief-empty');
    status.textContent = 'sem revisão';
    title.textContent = 'Ainda não há uma ronda de paper para resumir';
    copy.textContent = 'Executa uma recolha live válida; a decisão aparecerá aqui antes dos detalhes.';
    items.innerHTML = '<small>sem ativos</small>';
    return;
  }
  if (review.status === 'run_blocked') {
    container.classList.add('brief-alert');
    status.textContent = 'bloqueado';
    title.textContent = 'A ronda não foi validada';
    copy.textContent = (review.blockers || []).map((item) => item && item.message).filter(Boolean)[0] || 'Confirma a qualidade e as quotas antes de interpretar os sinais.';
  } else if (review.status === 'duplicate') {
    container.classList.add('brief-empty');
    status.textContent = 'sem nova ronda';
    title.textContent = 'A data de mercado ja foi processada';
    copy.textContent = (review.blockers || []).map((item) => item && item.message).filter(Boolean)[0] || 'Nao houve nova revisao de entradas nesta atualizacao.';
  } else if (buyCandidates.length) {
    container.classList.add('brief-watch');
    status.textContent = `${buyCandidates.length} para investigar`;
    title.textContent = 'Há sinais que chegaram ao limiar de compra';
    copy.textContent = `O score atingiu ${threshold}/100 em ${buyCandidates.join(', ')}. É um ponto de partida para investigação, não uma ordem.`;
  } else {
    container.classList.add('brief-watch');
    status.textContent = 'sem entrada';
    title.textContent = 'Não há entrada confirmada nesta ronda';
    const maxScore = signals.length ? Math.max(...signals.map((item) => Number(item.score)).filter(Number.isFinite)) : NaN;
    const maxCopy = Number.isFinite(maxScore) ? ` O score mais alto foi ${maxScore.toFixed(1)}/100.` : '';
    const topNear = nearCandidates[0];
    const gapCopy = topNear ? ` ${topNear.symbol} ainda fica ${Number(topNear.gap_to_buy ?? Math.max(0, threshold - Number(topNear.score || 0))).toFixed(1)} pontos abaixo do limiar; vigiar ${(topNear.watch_factors || []).join(', ') || 'os fatores do score'}.` : '';
    copy.textContent = `Nenhum ativo ultrapassou o limiar de compra (${threshold}/100).${maxCopy}${gapCopy} Acompanhar não é o mesmo que comprar.`;
  }
  const watch = nearCandidates.length ? nearCandidates : [...signals].sort((a, b) => Number(b.score || 0) - Number(a.score || 0)).slice(0, 3);
  items.innerHTML = watch.length ? watch.slice(0, 3).map((item) => `<button type="button" class="brief-asset" data-brief-symbol="${escapeHtml(item.symbol)}"><strong>${escapeHtml(item.symbol)}</strong><span>${score(item.score)}${item.gap_to_buy != null ? ` · faltam ${Number(item.gap_to_buy).toFixed(1)}` : ''}</span></button>`).join('') : '<small>sem ativos disponíveis</small>';
  items.querySelectorAll('[data-brief-symbol]').forEach((button) => button.addEventListener('click', () => selectAsset(button.dataset.briefSymbol)));
}

function renderFreshness() {
  const state = ui.state;
  const mode = state.meta?.mode === 'live' ? 'live' : 'demo';
  const quality = (state.quality || []).filter((item) => String(item.status).toUpperCase() === 'OK').length;
  const total = (state.quality || []).length;
  const outOfCohort = (state.quality || []).filter((item) => String(item.status).toUpperCase() === 'FORA_DA_COORTE').length;
  const qualityTotal = Math.max(0, total - outOfCohort);
  const cohort = state.meta?.cohort || {};
  const automation = state.automation || {};
  const automationHistory = state.automation_history || {};
  const automationState = String(automation.state || '').toLowerCase();
  const freshness = $('#freshness');
  if (automationState === 'failed') {
    freshness.title = automation.error || 'A última automação falhou.';
    freshness.innerHTML = `<span class="status-dot" style="background:var(--red)"></span><span>última ronda falhou</span>`;
  } else if (automationState === 'running') {
    freshness.title = 'A recolha local está em execução.';
    freshness.innerHTML = `<span class="status-dot" style="background:var(--yellow)"></span><span>ronda em execução</span>`;
  } else {
    if (cohort.rotated) freshness.title = `Coorte ativa: ${Number(cohort.active_symbols?.length || 0)} · ${Number(cohort.stale_symbols?.length || 0)} ativos com última leitura local`;
    else freshness.title = automation.completed_at ? `Última automação concluída: ${automation.completed_at}` : '';
    if (cohort.rotated && cohort.next_rotation_date) freshness.title += ` · próxima coorte ${Number(cohort.next_rotation_index || 0) + 1}/${Number(cohort.rotation_rounds || 0)} em ${cohort.next_rotation_date}`;
    const coverageNote = outOfCohort ? ` · ${outOfCohort} fora da coorte` : '';
    freshness.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(mode)} · ${quality}/${qualityTotal || total || 0} fontes OK${coverageNote}</span>`;
  }
}

function renderFilters() {
  renderSavedViews();
  const quick = [
    ['all', 'Todos'],
    ['strong', 'Score alto'],
    ['changed', 'Mudaram'],
    ['watchlist', `Favoritos (${ui.favorites.size})`],
    ['needs_review', 'Dados a rever'],
    ['coverage', 'Fora da coorte'],
  ];
  $('#quick-filters').innerHTML = quick.map(([key, label]) => `<button class="filter-button ${ui.quickFilter === key ? 'active' : ''}" data-quick-filter="${key}">${escapeHtml(label)}</button>`).join('');
  $('#quick-filters').querySelectorAll('[data-quick-filter]').forEach((button) => button.addEventListener('click', () => {
    ui.quickFilter = button.dataset.quickFilter;
    renderFilters();
    renderAssets();
  }));
  const sectors = ['Todos', ...new Set((ui.state.catalog || ui.state.universe || []).map((item) => item.sector).filter(Boolean))];
  $('#sector-filters').innerHTML = sectors.map((sector) => `<button class="filter-button ${ui.sector === sector ? 'active' : ''}" data-sector="${escapeHtml(sector)}">${escapeHtml(sector)}</button>`).join('');
  $('#sector-filters').querySelectorAll('[data-sector]').forEach((button) => button.addEventListener('click', () => {
    ui.sector = button.dataset.sector;
    renderAssets();
    renderFilters();
  }));
}

function renderSavedViews() {
  const select = $('#saved-views');
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">Vistas guardadas</option>${ui.savedViews.map((view, index) => `<option value="${index}">${escapeHtml(view.name)}</option>`).join('')}`;
  if (current !== '' && ui.savedViews[Number(current)]) select.value = current;
  $('#remove-view').disabled = !select.value;
}

function applySavedView(index) {
  const view = ui.savedViews[Number(index)];
  if (!view) return;
  ui.query = view.query;
  ui.sector = view.sector;
  ui.quickFilter = view.quickFilter;
  ui.assetSort = view.sort || 'score';
  $('#asset-search').value = ui.query;
  $('#asset-sort').value = ui.assetSort;
  renderFilters();
  renderAssets();
  $('#view-message').textContent = `Vista “${view.name}” aplicada.`;
}

function removeSelectedView() {
  const select = $('#saved-views');
  const index = Number(select.value);
  if (!Number.isInteger(index) || !ui.savedViews[index]) return;
  const name = ui.savedViews[index].name;
  ui.savedViews.splice(index, 1);
  localStorage.setItem('radar:saved-views', JSON.stringify(ui.savedViews));
  renderSavedViews();
  $('#view-message').textContent = `Vista “${name}” removida deste browser.`;
}

function saveCurrentView() {
  const input = $('#save-view-name');
  const message = $('#view-message');
  const name = input.value.trim().slice(0, 32);
  if (!name) {
    message.textContent = 'Dá um nome à vista antes de guardar.';
    input.focus();
    return;
  }
  const next = { name, query: ui.query, sector: ui.sector, quickFilter: ui.quickFilter, sort: ui.assetSort };
  const existing = ui.savedViews.findIndex((view) => view.name.toLowerCase() === name.toLowerCase());
  if (existing >= 0) ui.savedViews[existing] = next;
  else ui.savedViews.unshift(next);
  ui.savedViews = ui.savedViews.slice(0, 12);
  localStorage.setItem('radar:saved-views', JSON.stringify(ui.savedViews));
  renderSavedViews();
  input.value = '';
  message.textContent = `Vista “${name}” guardada neste browser.`;
}

function csvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

function exportFilteredAssetsCsv() {
  const signals = signalMap();
  const qualities = qualityMap();
  const rows = sortAssets(assetItems()).map((asset) => {
    const symbol = String(asset.symbol || '').toUpperCase();
    const signal = signals.get(symbol) || {};
    const quality = qualities.get(symbol) || {};
    return [symbol, asset.name || '', asset.sector || '', asset.provider || '', quality.status || 'Sem dados', signal.score ?? '', signal.action || 'Sem dados', signal.confidence ?? '', signal.price ?? ''];
  });
  const header = ['symbol', 'name', 'sector', 'provider', 'data_status', 'score', 'action', 'confidence', 'price'];
  const csv = [header, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n');
  const blob = new Blob([`\uFEFF${csv}\r\n`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `radar-watchlist-${ui.state?.meta?.as_of || 'snapshot'}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  const message = $('#view-message');
  if (message) message.textContent = `${rows.length} ativo${rows.length === 1 ? '' : 's'} exportado${rows.length === 1 ? '' : 's'} sem chamadas externas.`;
}

function renderSectorPulse() {
  const container = $('#sector-pulse');
  if (!container) return;
  const signals = signalMap();
  const groups = new Map();
  (ui.state.catalog || ui.state.universe || []).forEach((asset) => {
    const sector = String(asset.sector || 'Sem setor');
    const signal = signals.get(String(asset.symbol || '').toUpperCase());
    if (!groups.has(sector)) groups.set(sector, { sector, scores: [], signals: 0, buy: 0, total: 0 });
    const group = groups.get(sector);
    group.total += 1;
    if (!signal) return;
    const value = Number(signal.score);
    if (Number.isFinite(value)) group.scores.push(value);
    group.signals += 1;
    if (String(signal.action || '').toLowerCase().includes('compra')) group.buy += 1;
  });
  const rows = [...groups.values()]
    .map((group) => ({ ...group, average: group.scores.length ? group.scores.reduce((sum, value) => sum + value, 0) / group.scores.length : null }))
    .sort((left, right) => (right.average ?? -1) - (left.average ?? -1));
  if (!rows.length) {
    container.innerHTML = '<span class="sector-pulse-empty">Sem setores no snapshot.</span>';
    return;
  }
  const withData = rows.filter((row) => row.average != null);
  const visibleRows = (withData.length ? withData : rows).slice(0, 8);
  const hiddenCount = rows.length - visibleRows.length;
  const highlightThreshold = Number(ui.state.thresholds?.buy_score || 80);
  container.innerHTML = visibleRows.map((row) => {
    const average = row.average == null ? null : Number(row.average);
    const scoreLabel = average == null ? 'sem dados' : score(average);
    const standout = average != null && average >= highlightThreshold;
    const detail = average == null ? `${row.total} ativos · sem leitura` : `${row.signals}/${row.total} com leitura${row.buy ? ` · ${row.buy} sinal${row.buy === 1 ? '' : 's'} de compra` : ''}${standout ? ` · destaque >= ${highlightThreshold}` : ''}`;
    return `<button class="sector-pulse-card ${ui.sector === row.sector ? 'active' : ''} ${standout ? 'is-standout' : ''}" type="button" data-pulse-sector="${escapeHtml(row.sector)}"><span class="sector-pulse-top"><span>${escapeHtml(row.sector)}</span><strong>${escapeHtml(scoreLabel)}</strong></span><span class="sector-pulse-bar"><span style="width:${Math.max(0, Math.min(100, average || 0))}%"></span></span><small>${escapeHtml(detail)}</small></button>`;
  }).join('') + (hiddenCount ? `<span class="sector-pulse-more">+ ${hiddenCount} setor${hiddenCount === 1 ? '' : 'es'} sem leitura detalhada · usa os filtros abaixo para explorar</span>` : '');
  container.querySelectorAll('[data-pulse-sector]').forEach((button) => button.addEventListener('click', () => {
    ui.sector = button.dataset.pulseSector;
    renderFilters();
    renderSectorPulse();
    renderAssets();
  }));
}

function heatClass(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return 'heat-none';
  if (amount >= 75) return 'heat-strong';
  if (amount >= 60) return 'heat-positive';
  if (amount >= 40) return 'heat-neutral';
  return 'heat-weak';
}

function renderSectorHeatmap() {
  const container = $('#sector-heatmap');
  if (!container) return;
  const signals = signalMap();
  const groups = new Map();
  (ui.state.catalog || ui.state.universe || []).forEach((asset) => {
    const sector = String(asset.sector || 'Sem setor');
    if (!groups.has(sector)) groups.set(sector, { sector, assets: [], missing: 0 });
    const signal = signals.get(String(asset.symbol || '').toUpperCase());
    if (signal) groups.get(sector).assets.push({ ...asset, ...signal });
    else groups.get(sector).missing += 1;
  });
  const rows = [...groups.values()].sort((left, right) => {
    const leftAverage = left.assets.length ? left.assets.reduce((sum, item) => sum + Number(item.score || 0), 0) / left.assets.length : -1;
    const rightAverage = right.assets.length ? right.assets.reduce((sum, item) => sum + Number(item.score || 0), 0) / right.assets.length : -1;
    return rightAverage - leftAverage || left.sector.localeCompare(right.sector, 'pt');
  });
  if (!rows.length) {
    container.innerHTML = '<span class="heatmap-empty">Sem ativos no catálogo.</span>';
    return;
  }
  container.innerHTML = rows.slice(0, 12).map((group) => {
    const tiles = group.assets.sort((left, right) => Number(right.score || 0) - Number(left.score || 0)).slice(0, 16).map((asset) => {
      const symbol = String(asset.symbol || '').toUpperCase();
      return `<button class="heat-tile ${heatClass(asset.score)}" type="button" data-heat-symbol="${escapeHtml(symbol)}" title="${escapeHtml(`${symbol} · score ${score(asset.score)} · ${actionShort(asset.action)}`)}"><strong>${escapeHtml(symbol)}</strong><span>${escapeHtml(score(asset.score))}</span></button>`;
    }).join('');
    const missing = group.missing ? `<span class="heat-missing">+${group.missing} sem leitura</span>` : '';
    return `<div class="heatmap-group"><div class="heatmap-group-head"><span>${escapeHtml(group.sector)}</span><small>${group.assets.length ? `${group.assets.length} com score` : 'sem score'}${group.missing ? ` · ${group.missing} sem dados` : ''}</small></div><div class="heatmap-tiles">${tiles || '<span class="heatmap-no-signal">sem dados no snapshot</span>'}${missing}</div></div>`;
  }).join('');
  container.querySelectorAll('[data-heat-symbol]').forEach((button) => button.addEventListener('click', () => selectAsset(button.dataset.heatSymbol)));
}

function renderSectorRotation() {
  const container = $('#sector-rotation');
  if (!container) return;
  const signals = signalMap();
  const groups = new Map();
  (ui.state.catalog || ui.state.universe || []).forEach((asset) => {
    const signal = signals.get(String(asset.symbol || '').toUpperCase());
    if (!signal) return;
    const sector = String(asset.sector || 'Sem setor');
    if (!groups.has(sector)) groups.set(sector, { sector, relative: [], momentum: [], count: 0 });
    const group = groups.get(sector);
    const relative = Number(signal.relative_strength);
    const momentum = Number(signal.momentum);
    if (Number.isFinite(relative)) group.relative.push(relative);
    if (Number.isFinite(momentum)) group.momentum.push(momentum);
    group.count += 1;
  });
  const rows = [...groups.values()].map((group) => ({
    ...group,
    relative: group.relative.length ? group.relative.reduce((sum, value) => sum + value, 0) / group.relative.length : 50,
    momentum: group.momentum.length ? group.momentum.reduce((sum, value) => sum + value, 0) / group.momentum.length : 50,
  })).sort((left, right) => right.relative + right.momentum - left.relative - left.momentum);
  if (!rows.length) {
    container.innerHTML = '<span class="rotation-empty">Sem sinais suficientes para calcular rotação.</span>';
    return;
  }
  const quadrant = (relative, momentum) => relative >= 60 && momentum >= 60 ? ['leader', 'líder'] : relative < 60 && momentum >= 60 ? ['recovery', 'recuperação'] : relative >= 60 && momentum < 60 ? ['improving', 'a melhorar'] : ['lagging', 'atrasado'];
  const placed = [];
  const dots = rows.slice(0, 18).map((row, index) => {
    const [kind, label] = quadrant(row.relative, row.momentum);
    let x = Math.max(2, Math.min(98, row.relative));
    let y = Math.max(2, Math.min(98, row.momentum));
    for (let attempt = 0; attempt < 16 && placed.some((point) => Math.abs(point.x - x) < 8 || Math.abs(point.y - y) < 8); attempt += 1) {
      const angle = (index + attempt) * 0.9;
      const distance = 8 + Math.floor(attempt / 4) * 2;
      x = Math.max(4, Math.min(96, row.relative + Math.cos(angle) * distance));
      y = Math.max(5, Math.min(95, row.momentum + Math.sin(angle) * distance));
    }
    placed.push({ x, y });
    const short = row.sector.split(/\s+/).slice(0, 2).join(' ');
    return `<button class="rotation-dot ${kind}" type="button" data-rotation-sector="${escapeHtml(row.sector)}" style="left:${x}%; bottom:${y}%" title="${escapeHtml(`${row.sector} · ${label} · força ${score(row.relative)} · impulso ${score(row.momentum)}`)}"><strong>${escapeHtml(short)}</strong><small>${escapeHtml(score(row.relative))}/${escapeHtml(score(row.momentum))}</small></button>`;
  }).join('');
  container.innerHTML = `<div class="rotation-plot"><span class="rotation-axis x-axis">força relativa →</span><span class="rotation-axis y-axis">impulso ↑</span><span class="rotation-quadrant-label top-left">recuperação</span><span class="rotation-quadrant-label top-right">líderes</span><span class="rotation-quadrant-label bottom-left">atrasados</span><span class="rotation-quadrant-label bottom-right">a melhorar</span><span class="rotation-cross cross-x"></span><span class="rotation-cross cross-y"></span>${dots}</div><div class="rotation-foot"><span>cada ponto é a média do setor; clicar filtra o setor</span><span>${rows.length} setor${rows.length === 1 ? '' : 'es'} com leitura</span></div>`;
  container.onclick = (event) => {
    const button = event.target.closest('[data-rotation-sector]');
    if (!button || !container.contains(button)) return;
    ui.sector = button.dataset.rotationSector;
    renderFilters();
    renderSectorPulse();
    renderAssets();
  };
}

function renderCompareTray() {
  const tray = $('#compare-tray');
  const content = $('#compare-content');
  if (!tray || !content) return;
  const signals = signalMap();
  const selected = ui.compareSymbols.map((symbol) => signals.get(symbol)).filter(Boolean);
  tray.hidden = selected.length === 0;
  if (!selected.length) {
    content.innerHTML = '';
    return;
  }
  const metrics = [
    ['ação', (signal) => signal.action || 'Sem leitura'],
    ['score', (signal) => score(signal.score)],
    ['confiança', (signal) => score(signal.confidence)],
    ['impulso', (signal) => score(signal.momentum)],
    ['mercado relativo', (signal) => score(signal.relative_strength)],
    ['direção', (signal) => score(signal.trend)],
    ['risco penalizado', (signal) => score(signal.risk_penalty)],
  ];
  content.innerHTML = `<div class="compare-table-wrap"><table class="compare-table"><thead><tr><th>fator</th>${selected.map((signal) => `<th>${escapeHtml(signal.symbol)}<small>${escapeHtml(signal.sector || '')}</small></th>`).join('')}</tr></thead><tbody>${metrics.map(([label, getter]) => `<tr><th>${escapeHtml(label)}</th>${selected.map((signal) => `<td>${escapeHtml(getter(signal))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function assetItems() {
  const signals = signalMap();
  const qualities = qualityMap();
  const alertSymbols = new Set((ui.state.alerts || []).map((item) => String(item.symbol || '').toUpperCase()));
  const portfolioSymbols = new Set((ui.state.portfolio?.positions || []).map((item) => String(item.symbol || '').toUpperCase()));
  const assets = (ui.state.catalog || ui.state.universe || []).map((asset) => ({ ...asset, ...(signals.get(String(asset.symbol).toUpperCase()) || {}) }));
  return assets.filter((asset) => {
    const haystack = `${asset.symbol} ${asset.name || ''} ${asset.type || ''} ${asset.sector} ${asset.source_id}`.toLowerCase();
    const symbol = String(asset.symbol || '').toUpperCase();
    const hasSignal = Boolean(signals.get(symbol));
    const qualityStatus = String(qualities.get(symbol)?.status || '').toUpperCase();
    const outOfCohort = qualityStatus === 'FORA_DA_COORTE';
    const needsReview = !outOfCohort && (!hasSignal || (qualityStatus !== '' && qualityStatus !== 'OK'));
    const quickMatch = ui.quickFilter === 'all'
      || (ui.quickFilter === 'strong' && Number(asset.score) >= 60)
      || (ui.quickFilter === 'changed' && alertSymbols.has(symbol))
      || (ui.quickFilter === 'watchlist' && (favorite(symbol) || portfolioSymbols.has(symbol)))
      || (ui.quickFilter === 'needs_review' && needsReview)
      || (ui.quickFilter === 'coverage' && outOfCohort);
    return quickMatch && (!ui.query || haystack.includes(ui.query.toLowerCase())) && (ui.sector === 'Todos' || asset.sector === ui.sector);
  });
}

function sortAssets(items) {
  const actionOrder = { 'considerar compra': 0, 'manter/observar': 1, 'reduzir/evitar': 2, 'não agir': 3 };
  return [...items].sort((left, right) => {
    if (ui.assetSort === 'symbol') return String(left.symbol).localeCompare(String(right.symbol), 'pt');
    if (ui.assetSort === 'sector') return String(left.sector || '').localeCompare(String(right.sector || ''), 'pt') || String(left.symbol).localeCompare(String(right.symbol), 'pt');
    if (ui.assetSort === 'action') return (actionOrder[String(left.action || '').toLowerCase()] ?? 9) - (actionOrder[String(right.action || '').toLowerCase()] ?? 9);
    if (ui.assetSort === 'favorite') return Number(favorite(String(right.symbol))) - Number(favorite(String(left.symbol))) || Number(right.score || -1) - Number(left.score || -1);
    return Number(right.score || -1) - Number(left.score || -1);
  });
}

function renderAssetsLegacy() {
  let items = assetItems();
  const signals = signalMap();
  const qualities = qualityMap();
  items = sortAssets(items);
  if (!ui.query && ui.quickFilter === 'all') items = items.slice(0, 16);
  if (!items.length) {
    $('#asset-grid').innerHTML = '<div class="search-empty"><span class="empty-glyph">⌕</span><h3>Sem resultados</h3><p>Experimenta outro filtro ou pesquisa por símbolo, nome ou setor.</p></div>';
    renderCompareTray();
    return;
  }
  $('#asset-grid').innerHTML = items.map((asset) => {
    const symbol = String(asset.symbol || '').toUpperCase();
    const hasSignal = Boolean(signals.get(symbol));
    const qualityStatus = String(qualities.get(symbol)?.status || '').toUpperCase();
    const outOfCohort = qualityStatus === 'FORA_DA_COORTE';
    const qualityLabel = outOfCohort ? 'fora da coorte' : !hasSignal ? 'sem dados' : qualityStatus && qualityStatus !== 'OK' ? qualityStatus.toLowerCase() : 'fonte ok';
    const qualityClass = outOfCohort || !hasSignal ? 'missing' : qualityStatus && qualityStatus !== 'OK' ? 'warning' : 'good';
    return `<article class="asset-card ${ui.selected === symbol ? 'selected' : ''}" data-symbol="${escapeHtml(symbol)}" tabindex="0" role="button" aria-label="Analisar ${escapeHtml(symbol)}">
      <div class="asset-card-top"><div><div class="asset-symbol">${escapeHtml(symbol)}</div><div class="asset-sector">${escapeHtml(asset.name || asset.sector || 'sem nome')}</div></div><span class="asset-card-tools"><button class="asset-favorite ${favorite(symbol) ? 'is-favorite' : ''}" data-favorite="${escapeHtml(symbol)}" title="${favorite(symbol) ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}" aria-label="${favorite(symbol) ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}">${favorite(symbol) ? '★' : '☆'}</button><button class="asset-compare ${ui.compareSymbols.includes(symbol) ? 'is-compare' : ''}" data-compare="${escapeHtml(symbol)}" ${hasSignal ? '' : 'disabled'} title="${hasSignal ? (ui.compareSymbols.includes(symbol) ? 'Remover da comparação' : 'Adicionar à comparação') : 'Sem dados para comparar'}" aria-label="${hasSignal ? (ui.compareSymbols.includes(symbol) ? 'Remover da comparação' : 'Adicionar à comparação') : 'Sem dados para comparar'}">⇄</button><span class="action-pill ${hasSignal ? actionClass(asset.action) : 'action-none'}">${escapeHtml(hasSignal ? actionShort(asset.action) : 'Sem dados')}</span></span></div>
      <div class="asset-card-bottom"><span class="asset-price">${hasSignal ? money(asset.price, ui.state.meta?.currency || 'USD') : '—'}</span><span class="asset-score">${hasSignal ? `score ${score(asset.score)}` : 'configurar'}</span></div>
      <span class="asset-quality ${qualityClass}">${escapeHtml(qualityLabel)}</span>
    </article>`;
  }).join('');
  $('#asset-grid').querySelectorAll('[data-symbol]').forEach((card) => {
    card.addEventListener('click', () => selectAsset(card.dataset.symbol));
    card.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') selectAsset(card.dataset.symbol); });
  });
  $('#asset-grid').querySelectorAll('[data-favorite]').forEach((button) => button.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleFavorite(button.dataset.favorite);
  }));
  $('#asset-grid').querySelectorAll('[data-compare]').forEach((button) => button.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleCompare(button.dataset.compare);
  }));
  renderCompareTray();
}

function assetCardMarkup(asset, signals, qualities) {
  const symbol = String(asset.symbol || '').toUpperCase();
  const hasSignal = Boolean(signals.get(symbol));
  const quality = qualities.get(symbol) || {};
  const qualityStatus = String(quality.status || '').toUpperCase();
  const ageDays = Number(quality.age_days);
  const outOfCohort = qualityStatus === 'FORA_DA_COORTE';
  const freshness = Number.isFinite(ageDays) ? ` · ${ageDays === 0 ? 'hoje' : `${ageDays}d`}` : '';
  const qualityLabel = outOfCohort ? 'fora da coorte' : !hasSignal ? 'sem dados' : qualityStatus && qualityStatus !== 'OK' ? `${qualityStatus.toLowerCase()}${freshness}` : `fonte ok${freshness}`;
  const qualityClass = outOfCohort || !hasSignal ? 'missing' : qualityStatus && qualityStatus !== 'OK' ? 'warning' : 'good';
  return `<article class="asset-card ${ui.selected === symbol ? 'selected' : ''}" data-symbol="${escapeHtml(symbol)}" tabindex="0" role="button" aria-label="Analisar ${escapeHtml(symbol)}">
    <div class="asset-card-top"><div><div class="asset-symbol">${escapeHtml(symbol)}</div><div class="asset-sector">${escapeHtml(asset.name || asset.sector || 'sem nome')}</div></div><span class="asset-card-tools"><button class="asset-favorite ${favorite(symbol) ? 'is-favorite' : ''}" data-favorite="${escapeHtml(symbol)}" title="${favorite(symbol) ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}" aria-label="${favorite(symbol) ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}">${favorite(symbol) ? '★' : '☆'}</button><button class="asset-compare ${ui.compareSymbols.includes(symbol) ? 'is-compare' : ''}" data-compare="${escapeHtml(symbol)}" ${hasSignal ? '' : 'disabled'} title="${hasSignal ? (ui.compareSymbols.includes(symbol) ? 'Remover da comparação' : 'Adicionar à comparação') : 'Sem dados para comparar'}" aria-label="${hasSignal ? (ui.compareSymbols.includes(symbol) ? 'Remover da comparação' : 'Adicionar à comparação') : 'Sem dados para comparar'}">⇄</button><span class="action-pill ${hasSignal ? actionClass(asset.action) : 'action-none'}">${escapeHtml(hasSignal ? actionShort(asset.action) : 'Sem dados')}</span></span></div>
    <div class="asset-card-bottom"><span class="asset-price">${hasSignal ? money(asset.price, ui.state.meta?.currency || 'USD') : '—'}</span><span class="asset-score">${hasSignal ? `score ${score(asset.score)}` : 'sem leitura'}</span></div>
    <span class="asset-quality ${qualityClass}">${escapeHtml(qualityLabel)}</span>
  </article>`;
}

function renderAssetCards(container, items, emptyCopy = 'Sem resultados. Experimenta outra pesquisa.') {
  if (!container) return;
  const signals = signalMap();
  const qualities = qualityMap();
  if (!items.length) {
    container.innerHTML = `<div class="search-empty"><span class="empty-glyph">⌕</span><h3>Sem leituras para mostrar</h3><p>${escapeHtml(emptyCopy)}</p></div>`;
    return;
  }
  container.innerHTML = items.map((asset) => assetCardMarkup(asset, signals, qualities)).join('');
  container.querySelectorAll('[data-symbol]').forEach((card) => {
    card.addEventListener('click', () => selectAsset(card.dataset.symbol));
    card.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectAsset(card.dataset.symbol); } });
  });
  container.querySelectorAll('[data-favorite]').forEach((button) => button.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleFavorite(button.dataset.favorite);
  }));
  container.querySelectorAll('[data-compare]').forEach((button) => button.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleCompare(button.dataset.compare);
  }));
}

function priorityHighlightItems(items) {
  const signals = signalMap();
  const portfolioSymbols = new Set((ui.state.portfolio?.positions || []).map((item) => String(item.symbol || '').toUpperCase()));
  const favorites = new Set([...ui.favorites].map((item) => String(item).toUpperCase()));
  const ranked = [...items].sort((left, right) => {
    const leftPriority = Number(portfolioSymbols.has(String(left.symbol).toUpperCase())) * 2 + Number(favorites.has(String(left.symbol).toUpperCase()));
    const rightPriority = Number(portfolioSymbols.has(String(right.symbol).toUpperCase())) * 2 + Number(favorites.has(String(right.symbol).toUpperCase()));
    return rightPriority - leftPriority || Number(right.score || -1) - Number(left.score || -1);
  });
  const readable = ranked.filter((asset) => signals.has(String(asset.symbol || '').toUpperCase()));
  return readable.slice(0, 3);
}

function renderAssets() {
  const allItems = sortAssets(assetItems());
  const filteredItems = ui.query || ui.quickFilter !== 'all' || ui.sector !== 'Todos' ? allItems : allItems;
  const readableItems = filteredItems.filter((asset) => signalMap().has(String(asset.symbol || '').toUpperCase()));
  const highlightItems = ui.query || ui.quickFilter !== 'all' || ui.sector !== 'Todos' ? readableItems.slice(0, 3) : priorityHighlightItems(filteredItems);
  const highlightTitle = $('#asset-highlight-title');
  const highlightNote = $('#asset-highlight-note');
  if (highlightTitle) highlightTitle.textContent = ui.query ? `Resultados para “${ui.query}”` : '3 leituras para começar';
  if (highlightNote) highlightNote.textContent = ui.query ? `${highlightItems.length} leitura(s) nesta pesquisa · sem novas chamadas` : 'Sinais disponíveis, priorizando favoritos e posições da carteira.';
  renderAssetCards($('#asset-highlights'), highlightItems, ui.query ? 'Não há ativos no catálogo local com esse nome.' : 'Ainda não há leituras disponíveis no snapshot atual.');
  const advanced = $('#advanced-explorer');
  const grid = $('#asset-grid');
  if (grid) renderAssetCards(grid, advanced?.open ? filteredItems : [], advanced?.open ? 'Experimenta outro filtro ou pesquisa por símbolo, nome ou setor.' : 'Abre o catálogo completo para ver todos os ativos.');
  renderCompareTray();
}

function renderPortfolioFocus() {
  const container = $('#portfolio-focus-metrics');
  if (!container) return;
  const positions = ui.state.portfolio?.positions || [];
  const signals = signalMap();
  const monitor = ui.state.portfolio_monitor || {};
  const selectedCount = Number(monitor.selected_count || 0);
  const coveredCount = Number(monitor.covered_count || 0);
  const nextCount = Number(monitor.next_count || monitor.max_assets_per_run || 0);
  const budget = (ui.state.network_plan?.daily_budgets || []).find((item) => item.provider === 'yahoo_finance') || (ui.state.network_plan?.daily_budgets || []).find((item) => item.provider === 'alpha_vantage');
  const reserve = Number.isFinite(Number(budget?.reserve)) ? Number(budget.reserve) : 5;
  const remaining = budget?.remaining == null ? '—' : Number(budget.remaining).toFixed(0);
  const monitoringLabel = selectedCount ? `${coveredCount}/${selectedCount}` : `0/${nextCount || positions.length || 0}`;
  const monitoringNote = Number(monitor.trimmed_count || 0) > 0 ? `${selectedCount}/${monitor.requested_count} após preservar a reserva` : selectedCount ? 'posições prioritárias desta ronda' : nextCount ? `${nextCount} prioritárias na próxima ronda live` : 'a aguardar seleção live';
  container.innerHTML = `<div><span>posições</span><strong>${positions.length}</strong></div><div><span>monitorização</span><strong>${monitoringLabel}</strong><small>${monitoringNote}</small></div><div><span>reserva live</span><strong>${monitor?.reserve_calls || reserve} chamadas</strong><small>${remaining} restantes no orçamento</small></div>`;
  const queue = $('#portfolio-focus-queue');
  const nextQueue = Array.isArray(monitor.next_queue) ? monitor.next_queue : [];
  if (queue) {
    const shown = nextQueue.slice(0, 3);
    queue.innerHTML = shown.length
      ? `<span>próxima fila</span>${shown.map((item) => `<button type="button" data-queue-symbol="${escapeHtml(item.symbol)}"><strong>${escapeHtml(item.symbol)}</strong><small>${escapeHtml(item.reason || 'prioridade local')}</small></button>`).join('')}${nextQueue.length > shown.length ? `<em>+${nextQueue.length - shown.length}</em>` : ''}`
      : '<span>próxima fila</span><small>a fila aparece quando existirem posições elegíveis</small>';
    queue.querySelectorAll('[data-queue-symbol]').forEach((button) => button.addEventListener('click', () => selectAsset(button.dataset.queueSymbol)));
  }
}

function renderDetail(signal, note = '') {
  if (!signal) {
    const catalogItem = (ui.state.catalog || []).find((item) => String(item.symbol).toUpperCase() === ui.selected);
    if (!catalogItem) {
      $('#asset-detail').innerHTML = '<div class="empty-detail"><span class="empty-glyph">?</span><h3>Sem leitura disponível</h3><p>Este ativo não aparece no catálogo local.</p></div>';
      return;
    }
    $('#asset-detail').innerHTML = `<div class="detail-head"><div><div class="detail-title"><h3>${escapeHtml(catalogItem.symbol)}</h3><span>${escapeHtml(catalogItem.type || 'Ativo')}</span></div><p class="detail-sub">${escapeHtml(catalogItem.name || '')} · ${escapeHtml(catalogItem.sector || '')}</p></div><div class="detail-price">sem dados</div></div>
      <div class="detail-callout"><div class="detail-callout-top"><strong>Não agir</strong><span class="action-pill action-none">fora do radar</span></div><p>Este ativo está no catálogo de pesquisa, mas ainda não tem uma leitura no snapshot atual.</p></div>
      <div class="detail-grid"><div><span class="metric-label">fonte sugerida</span><span class="metric-value">${escapeHtml(catalogItem.provider || '—')}</span></div><div><span class="metric-label">setor</span><span class="metric-value">${escapeHtml(catalogItem.sector || '—')}</span></div><div><span class="metric-label">próximo passo</span><span class="metric-value">configurar</span></div></div>
      <div class="detail-foot"><span>O catálogo é local. Só o botão live usa quota de API.</span><span class="detail-actions"><button class="card-action live-action" id="live-analysis">Analisar live <span>↗</span></button><button class="card-action report-action" id="export-report">PDF <span>↓</span></button><button class="card-action report-action" id="export-markdown">Markdown <span>↓</span></button></span></div>`;
    $('#live-analysis').addEventListener('click', () => runLiveAnalysis(catalogItem.symbol));
    $('#export-report').addEventListener('click', () => exportReport(catalogItem.symbol));
    $('#export-markdown').addEventListener('click', () => exportReport(catalogItem.symbol, 'md'));
    return;
  }
  const factors = [
    ['Impulso do preço', 'momentum'], ['Comparação com o mercado', 'relative_strength'], ['Direção do preço', 'trend'],
    ['Atividade de negociação', 'volume'], ['Clima das notícias', 'news'], ['Ambiente económico', 'macro'],
  ];
  const scoreReading = metricReading('score', signal.score);
  const confidenceReading = metricReading('confidence', signal.confidence);
  const riskReading = metricReading('risk_penalty', signal.risk_penalty);
  const drawdownReading = metricReading('drawdown', signal.drawdown);
  const horizons = signal.horizons || {};
  const position = (ui.state.portfolio?.positions || []).find((item) => String(item.symbol).toUpperCase() === String(signal.symbol).toUpperCase());
  const basis = position?.acquisition_analysis;
  const journal = journalFor(signal.symbol, signal.date);
  const assetOutcomes = ui.state.outcomes?.summary?.by_symbol?.[String(signal.symbol).toUpperCase()] || {};
  const assetChanges = (ui.state.alerts || []).filter((item) => String(item.symbol || '').toUpperCase() === String(signal.symbol).toUpperCase()).slice(0, 3);
  const assetHistory = (ui.state.signal_history || []).filter((item) => String(item.symbol || '').toUpperCase() === String(signal.symbol).toUpperCase()).slice(-8);
  const qualityInfo = qualityMap().get(String(signal.symbol).toUpperCase()) || {};
  const persistedUsage = (ui.state.on_demand || []).find((item) => String(item.symbol || '').toUpperCase() === String(signal.symbol).toUpperCase())?.usage_details;
  const usage = ui.lastUsage && String(ui.lastUsage.symbol || '').toUpperCase() === String(signal.symbol).toUpperCase() ? ui.lastUsage : (persistedUsage && Object.keys(persistedUsage).length ? persistedUsage : null);
  if (usage) note = `${note} · ${usage.provider || 'provider'} · TTL ${Math.max(1, Math.round(Number(usage.ttl_seconds || 0) / 3600))}h${usage.context_reused ? ' · contexto reutilizado' : ''}`;
  if (qualityInfo.fallback_used) note = `${note} · fallback ${qualityInfo.provider_requested || 'provider'} → ${qualityInfo.provider_used || qualityInfo.source || 'alternativa'}`;
  const acquisitionBlock = position ? `<div class="detail-callout acquisition-callout"><div class="detail-callout-top"><strong>A tua compra</strong><span class="action-pill ${basis?.available && Number(basis.pnl_pct) < 0 ? 'action-sell' : 'action-hold'}">${basis?.available ? escapeHtml(`${percent(basis.pnl_pct)} · ${basis.level}`) : 'preço desconhecido'}</span></div><p>${escapeHtml(basis?.available ? basis.meaning : (basis?.meaning || 'Confirma o preço médio de compra na corretora.'))}</p><small class="callout-reading">${escapeHtml(basis?.action || 'Sem comparação com o preço de aquisição.')}</small></div>` : '';
  const changeBlock = assetChanges.length ? `<div class="change-box"><div class="outcome-head"><span class="card-label">mudanças recentes</span><span>desde o snapshot anterior</span></div>${assetChanges.map((event) => `<div class="change-row"><strong>${escapeHtml(event.from_action || '—')} → ${escapeHtml(event.to_action || '—')}</strong><span>${event.score_delta == null ? 'score sem variação' : `score ${Number(event.score_delta) >= 0 ? '+' : ''}${Number(event.score_delta).toFixed(1)}`}</span><small>${escapeHtml(event.reason || 'mudança registada no snapshot')}</small></div>`).join('')}</div>` : '';
  const journalBlock = `<div class="journal-box"><label for="journal-note">Nota pessoal desta leitura</label><textarea id="journal-note" rows="3" maxlength="2000" placeholder="O que queres confirmar antes de agir?">${escapeHtml(journal?.note || '')}</textarea><div class="journal-footer"><span>Fica guardada localmente e aparece no relatório.</span><button class="card-action" id="save-journal">Guardar nota <span>✓</span></button></div><div class="form-message" id="journal-message" role="status"></div></div>`;
  const historyBlock = assetHistory.length ? `<div class="history-box"><div class="outcome-head"><span class="card-label">histórico local do score</span><span>descritivo · ${assetHistory.length} leituras</span></div><div class="history-bars">${assetHistory.map((item) => { const value = Number(item.score); const width = Number.isFinite(value) ? Math.max(3, Math.min(100, value)) : 3; return `<div class="history-point" title="${escapeHtml(`${item.as_of} · score ${score(value)} · ${actionShort(item.action)}`)}"><span class="history-bar"><span style="height:${width}%"></span></span><strong>${escapeHtml(score(value))}</strong><small>${escapeHtml(String(item.as_of || '').slice(5))}</small></div>`; }).join('')}</div><p class="history-note">A evolução ajuda a contextualizar a leitura atual; não estima o próximo movimento.</p></div>` : '';
  const horizonOrder = ['short', 'medium', 'long'];
  $('#asset-detail').innerHTML = `<div class="detail-head"><div><div class="detail-title"><h3>${escapeHtml(signal.symbol)}</h3><span>${escapeHtml(signal.sector || '')}</span></div><p class="detail-sub">última leitura · ${escapeHtml(dateLabel(signal.date))}</p></div><div class="detail-price">${money(signal.price, ui.state.meta?.currency || 'USD')}</div></div>
    <div class="detail-callout"><div class="detail-callout-top"><strong>${escapeHtml(signal.action || 'Sem ação')}</strong><span class="action-pill ${actionClass(signal.action)}">${escapeHtml(`score ${score(signal.score)} · ${scoreReading.level}`)}</span></div><p>${escapeHtml(signal.notes || 'O radar não deixou uma explicação adicional.')}</p><small class="callout-reading">${escapeHtml(`Score ${scoreReading.band}: ${scoreReading.meaning}`)}</small></div>${changeBlock}${historyBlock}
    <div class="horizon-grid">${horizonOrder.map((key) => { const view = horizons[key] || {}; return `<article class="horizon-card"><span class="metric-label">${escapeHtml(view.label || key)}</span><strong>${escapeHtml(view.action || 'Sem leitura')}</strong><div class="horizon-score"><span>${score(view.score)}/100</span><span class="factor-bar"><span style="width:${Math.max(0, Math.min(100, Number(view.score) || 0))}%"></span></span></div><p>${escapeHtml(view.focus || 'contexto indisponível')}</p></article>`; }).join('')}</div>${acquisitionBlock}
    ${journalBlock}<div class="detail-grid"><div><span class="metric-label">confiança</span><span class="metric-value">${score(signal.confidence)}/100</span><span class="metric-reading">${escapeHtml(confidenceReading.level)} · ${escapeHtml(confidenceReading.meaning)}</span></div><div><span class="metric-label">risco penalizado</span><span class="metric-value">${score(signal.risk_penalty)}/30</span><span class="metric-reading">${escapeHtml(riskReading.level)} · ${escapeHtml(riskReading.meaning)}</span></div><div><span class="metric-label">drawdown</span><span class="metric-value">${percent(signal.drawdown)}</span><span class="metric-reading">${escapeHtml(drawdownReading.level)} · ${escapeHtml(drawdownReading.meaning)}</span></div></div>
    <div class="factor-list">${factors.map(([label, key]) => { const value = signal[key]; const reading = personalizedMetricReading(key, value, ui.state.catalog?.find((item) => String(item.symbol).toUpperCase() === String(signal.symbol).toUpperCase()), signal); return `<div class="factor-row"><span class="factor-name"><span>${escapeHtml(label)}</span><small>${escapeHtml(reading.level)} · ${escapeHtml(reading.personalized)}</small></span><span class="factor-bar"><span style="width:${Math.max(0, Math.min(100, Number(value) || 0))}%"></span></span><strong>${score(value)}</strong></div>`; }).join('')}</div>
    <details class="metric-guide"><summary>O que significam estes numeros?</summary><div class="guide-grid"><p><strong>Pontuação</strong> junta os sinais numa nota de 0 a 100; não é uma probabilidade de lucro.</p><p><strong>Consistência</strong> mede o acordo entre os sinais e o histórico disponível.</p><p><strong>Risco técnico</strong> penaliza instabilidade e quedas; quanto maior, mais cuidado pede.</p><p><strong>Queda desde o pico</strong> mostra quanto falta para voltar ao máximo recente.</p><p><strong>Impulso do preço</strong> mede se o movimento recente ganhou ou perdeu força.</p><p><strong>Ambiente económico</strong> resume inflação, juros e moeda em palavras simples; ajuda a ler o contexto, não prevê o preço.</p></div></details>
    <div class="detail-foot"><span>${escapeHtml(note || 'A análise considera o mercado de comparação, o ambiente económico e as fontes disponíveis.')}</span><span class="detail-actions"><button class="card-action live-action" id="live-analysis">Analisar live <span>↗</span></button><button class="card-action" id="run-analysis">Ver snapshot <span>→</span></button><button class="card-action report-action" id="export-report">PDF <span>↓</span></button><button class="card-action report-action" id="export-markdown">Markdown <span>↓</span></button></span></div>`;
  if (Object.keys(assetOutcomes).length) {
    const outcomeBox = document.createElement('div');
    outcomeBox.className = 'outcome-box';
    outcomeBox.innerHTML = `<div class="outcome-head"><span class="card-label">evidência histórica deste ativo</span><span>não é previsão</span></div><p>Outcomes fechados anteriormente para este símbolo no mesmo modo.</p>${Object.entries(assetOutcomes).map(([horizon, value]) => `<div class="outcome-row"><strong>${escapeHtml(horizon)} obs.</strong><span>${Number(value.records || 0)} registos</span><span>${value.positive_rate == null ? '—' : `${(Number(value.positive_rate) * 100).toFixed(1)}% positivos`}</span><span>${value.average_return == null ? '—' : `${(Number(value.average_return) * 100).toFixed(2)}% média`}</span></div>`).join('')}`;
    $('#asset-detail').querySelector('.detail-grid')?.before(outcomeBox);
  }
  $('#live-analysis').addEventListener('click', () => runLiveAnalysis(signal.symbol));
  $('#run-analysis').addEventListener('click', () => runAnalysis(signal.symbol));
  $('#export-report').addEventListener('click', () => exportReport(signal.symbol));
  $('#export-markdown').addEventListener('click', () => exportReport(signal.symbol, 'md'));
  $('#save-journal').addEventListener('click', () => saveJournal(signal.symbol, signal.date));
}

async function saveJournal(symbol, asOf) {
  const note = $('#journal-note')?.value || '';
  const button = $('#save-journal');
  const message = $('#journal-message');
  if (button) { button.disabled = true; button.textContent = 'A guardar…'; }
  try {
    const response = await fetch('/api/journal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, as_of: asOf, note }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível guardar a nota.');
    ui.state = result;
    renderAll();
    renderDetail(signalMap().get(String(symbol).toUpperCase()), 'Nota pessoal atualizada; o texto fica apenas neste computador.');
  } catch (error) {
    if (message) { message.className = 'form-message error'; message.textContent = error.message; }
    if (button) { button.disabled = false; button.innerHTML = 'Guardar nota <span>✓</span>'; }
  }
}

function exportReport(symbol, format = 'pdf') {
  window.location.href = `/api/report?format=${format}&symbol=${encodeURIComponent(symbol)}`;
}

function exportPortfolioReport() {
  window.location.href = '/api/portfolio-report?format=pdf';
}

function reportText(value) {
  return String(value ?? '—').replace(/[\r\n]+/g, ' ').replace(/\|/g, '/').trim();
}

function exportAlertsReport() {
  const state = ui.state || {};
  const items = ui.alertItems || [];
  const lines = [
    '# Relatório local de supervisão',
    '',
    `**Snapshot:** ${reportText(state.meta?.as_of)} · **Modo:** ${reportText(state.meta?.mode)}`,
    `**Filtro:** ${reportText(ui.alertFilter)} · **Pesquisa:** ${reportText(ui.alertQuery || 'sem pesquisa')} · **Ordenação:** ${reportText(ui.alertSort)}`,
    '',
    '> Este ficheiro é uma fotografia local dos alertas filtrados. Não gera ordens nem chama providers.',
    '',
    '## Alertas',
    '',
    '| Estado | Categoria | Título | Razão |',
    '|---|---|---|---|',
  ];
  if (!items.length) lines.push('| — | — | Nenhum alerta neste recorte | — |');
  else items.forEach((item) => lines.push(`| ${item.reviewed ? 'revisto' : 'por rever'} | ${reportText(item.category)} | ${reportText(item.title)} | ${reportText(item.detail)} |`));
  const blob = new Blob([`${lines.join('\n')}\n`], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `radar-supervisao-${state.meta?.as_of || 'snapshot'}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function runLiveAnalysisWithoutPlan(symbol) {
  const confirmed = window.confirm(`Analisar ${symbol} com dados live?\n\nEsta ação pode consumir quota das APIs. O catálogo e o relatório local não consomem quota.`);
  if (!confirmed) return;
  const button = $('#live-analysis');
  if (button) { button.disabled = true; button.textContent = 'A recolher…'; }
  try {
    const response = await fetch('/api/live-analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'A análise live falhou.');
    ui.state = result.state;
    ui.selected = symbol;
    ui.lastUsage = { ...(result.usage_details || {}), ...(result.usage || {}), symbol };
    renderAll();
    renderDetail(result.signal, result.cached ? 'Resultado em cache; não foi feita nova chamada.' : 'Atualizado live agora; só esta ação consumiu quota.');
  } catch (error) {
    if (button) { button.disabled = false; button.innerHTML = 'Analisar live <span>↗</span>'; }
    window.alert(error.message);
  }
}

async function runLiveAnalysis(symbol) {
  let plan;
  try {
    const planResponse = await fetch(`/api/live-plan?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store' });
    plan = await planResponse.json();
    if (!planResponse.ok) throw new Error(plan.error || 'Não foi possível preparar a análise live.');
  } catch (error) {
    window.alert(error.message);
    return;
  }
  if (plan.provider_cooldown?.active) {
    const blockedProviders = (plan.provider_cooldowns || []).map((item) => item.provider).join(', ') || plan.provider || 'provider externo';
    window.alert(`${blockedProviders} está em cooldown local por mais ${plan.provider_cooldown.remaining_seconds || 0}s após rate limit. Tenta novamente depois; não foi feita nenhuma chamada.`);
    return;
  }
  if (plan.budget_blocked) {
    window.alert(`${plan.budget_message || 'O orçamento diário local não cobre esta análise.'}\n\nNão foi feita nenhuma chamada.`);
    return;
  }
  const cacheLine = plan.cache?.status === 'fresh' ? 'Cache fresco: nenhuma chamada externa prevista.' : `${plan.estimated_calls || 0} chamadas externas previstas.`;
  const contextLine = plan.context?.status === 'reused' ? 'Contexto macro/notícias será reutilizado.' : 'Contexto macro/notícias será recolhido.';
  const budgetLine = (plan.daily_budgets || []).filter((item) => item.limit != null).map((item) => `${item.provider}: ${item.remaining} restantes de ${item.limit}`).join(' · ');
  const keyLine = plan.missing_keys?.length ? `Chaves em falta: ${plan.missing_keys.join(', ')}.` : 'Chaves necessárias configuradas.';
  const confirmed = window.confirm(`Analisar ${symbol} com dados live?\n\n${cacheLine}\n${contextLine}\n${budgetLine ? `Orçamento local: ${budgetLine}\n` : ''}${keyLine}\n\n${plan.message || ''}`);
  if (!confirmed) return;
  const button = $('#live-analysis');
  if (button) { button.disabled = true; button.textContent = 'A recolher…'; }
  try {
    const response = await fetch('/api/live-analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'A análise live falhou.');
    ui.state = result.state;
    ui.selected = symbol;
    ui.lastUsage = { ...(result.usage_details || {}), ...(result.usage || {}), symbol };
    renderAll();
    renderDetail(result.signal, result.cached ? 'Resultado em cache; não foi feita nova chamada.' : 'Atualizado live agora; só esta ação consumiu quota.');
  } catch (error) {
    if (button) { button.disabled = false; button.innerHTML = 'Analisar live <span>↗</span>'; }
    window.alert(error.message);
  }
}

async function runAnalysis(symbol) {
  const button = $('#run-analysis');
  if (button) { button.disabled = true; button.textContent = 'A calcular…'; }
  try {
    const response = await fetch(`/api/analyze?symbol=${encodeURIComponent(symbol)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível ler o ativo.');
    ui.selected = symbol;
    renderDetail(result.signal, 'Leitura confirmada a partir do último snapshot local.');
  } catch (error) {
    if (button) { button.disabled = false; button.textContent = 'Correr leitura local →'; }
    window.alert(error.message);
  }
}

function selectAsset(symbol) {
  ui.selected = String(symbol).toUpperCase();
  const signal = signalMap().get(ui.selected);
  const advanced = $('#advanced-explorer');
  if (advanced && !advanced.open) advanced.open = true;
  renderAssets();
  renderDetail(signal);
  document.querySelector('#asset-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderPortfolio() {
  const portfolio = ui.state.portfolio || { positions: [], market_value: 0 };
  $('#portfolio-total').textContent = money(portfolio.market_value || 0, portfolio.market_value_currency || 'EUR');
  $('#portfolio-valuation-note').textContent = portfolio.valuation_note || 'Valores comparáveis na moeda base da carteira.';
  $('#portfolio-updated').textContent = portfolio.updated_at ? `guardada ${new Date(portfolio.updated_at).toLocaleDateString('pt-PT')}` : 'ainda vazio';
  const sectorRows = portfolio.sector_exposure || [];
  const correlations = portfolio.correlation_pairs || [];
  const riskRows = portfolio.risk_contribution || [];
  $('#portfolio-sector-exposure').innerHTML = sectorRows.length || correlations.length ? `${sectorRows.length ? `<div class="sector-exposure-head"><span class="card-label">concentração por setor</span><span class="position-sector">${portfolio.sector_exposure_approximate ? 'EUR normalizado · câmbio do extrato' : 'base comparável'}</span></div><div class="sector-exposure-list">${sectorRows.map((item) => `<div class="sector-exposure-row"><span>${escapeHtml(item.sector)}</span><strong>${percent(item.weight)}</strong><span class="sector-bar"><span style="width:${Math.max(0, Math.min(100, Number(item.weight || 0) * 100))}%"></span></span></div>`).join('')}</div>` : ''}${correlations.length ? `<div class="correlation-block"><div class="sector-exposure-head"><span class="card-label">correlações elevadas</span><span class="position-sector">retornos diários · aproximado</span></div>${correlations.map((item) => `<div class="correlation-row"><span>${escapeHtml(item.left)} · ${escapeHtml(item.right)}</span><strong>${Number(item.correlation).toFixed(2)}</strong></div>`).join('')}</div>` : ''}` : '';
  if (riskRows.length) {
    const riskBlock = document.createElement('div');
    riskBlock.className = 'risk-contribution-block';
    const volatility = Number(portfolio.annualized_volatility);
    riskBlock.innerHTML = `<div class="sector-exposure-head"><span class="card-label">contribuição para variabilidade</span><span class="position-sector">${portfolio.risk_observations || 0} observações${Number.isFinite(volatility) ? ` · anualizada ${percent(volatility)}` : ''}</span></div><p class="risk-help">Estimativa por covariância dos retornos locais; não é previsão nem análise dos ativos dentro de ETFs.</p>${riskRows.slice(0, 8).map((item) => { const contribution = Number(item.contribution_pct); const width = Math.max(2, Math.min(100, Math.abs(contribution) * 100)); return `<div class="risk-contribution-row"><span><strong>${escapeHtml(item.symbol)}</strong><small>${percent(item.weight)} do inventário</small></span><span class="risk-contribution-bar"><span class="${contribution < 0 ? 'negative' : ''}" style="width:${width}%"></span></span><strong class="risk-contribution-value">${contribution >= 0 ? '+' : ''}${percent(contribution)}</strong></div>`; }).join('')}`;
    $('#portfolio-sector-exposure').appendChild(riskBlock);
  } else if ((portfolio.positions || []).length) {
    const coverageBlock = document.createElement('div');
    coverageBlock.className = 'risk-contribution-block';
    coverageBlock.innerHTML = '<div class="sector-exposure-head"><span class="card-label">contribuição para variabilidade</span><span class="position-sector">sem cobertura suficiente</span></div><p class="risk-help">O ledger local ainda não tem 20 observações comuns para as posições atuais. A app não inventa uma estimativa; a cobertura aparece quando houver histórico comparável.</p>';
    $('#portfolio-sector-exposure').appendChild(coverageBlock);
  }
  const targetContainer = $('#portfolio-targets');
  const driftRows = portfolio.sector_drift || [];
  if (!targetContainer || !driftRows.length) {
    if (targetContainer) targetContainer.innerHTML = '';
  } else {
    const targetTotal = Number(portfolio.target_total || 0);
    targetContainer.innerHTML = `<div class="target-heading"><span class="card-label">metas por setor</span><span>${targetTotal ? `guardadas ${percent(targetTotal)}` : 'opcional · sem meta guardada'}</span></div><p class="target-help">Define uma meta de peso por setor. O desvio é informativo e não cria ordens; podes deixar parte da carteira sem meta.</p><form id="portfolio-target-form" class="target-form"><div class="target-grid">${driftRows.map((item) => { const actual = Number(item.actual || 0); const target = item.target == null ? '' : (Number(item.target) * 100).toFixed(1); const drift = item.drift == null ? 'sem meta' : `${Number(item.drift) >= 0 ? '+' : ''}${percent(item.drift)}`; const gap = Number(item.value_gap); const currency = portfolio.market_value_currency && portfolio.market_value_currency !== 'MIX' ? portfolio.market_value_currency : ''; const adjustment = item.drift == null || !Number.isFinite(gap) ? 'sem meta' : `${gap > 0 ? 'reduzir' : 'aumentar'} ${currency ? money(Math.abs(gap), currency) : `${Math.abs(gap).toFixed(2)} aprox.`}`; return `<label class="target-row"><span><strong>${escapeHtml(item.sector)}</strong><small>atual ${percent(actual)} · ${escapeHtml(drift)}</small><small class="target-adjustment">${escapeHtml(adjustment)}</small></span><span class="target-input-wrap"><input type="number" min="0" max="100" step="0.1" value="${escapeHtml(target)}" data-target-sector="${escapeHtml(item.sector)}" aria-label="Meta para ${escapeHtml(item.sector)}"><span>%</span></span></label>`; }).join('')}</div><div class="target-actions"><span id="target-message" class="form-message" role="status"></span><button class="secondary-button" id="clear-portfolio-targets" type="button">Limpar metas</button><button class="primary-button" type="submit">Guardar metas <span>✓</span></button></div></form>`;
    const targetForm = $('#portfolio-target-form');
    targetForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const targets = {};
      let total = 0;
      let invalid = false;
      targetForm.querySelectorAll('[data-target-sector]').forEach((input) => {
        const raw = input.value.trim();
        if (!raw) return;
        const value = Number(raw);
        if (!Number.isFinite(value) || value < 0 || value > 100) invalid = true;
        else { targets[input.dataset.targetSector] = value / 100; total += value / 100; }
      });
      const message = $('#target-message');
      if (invalid || total > 1.000001) { message.className = 'form-message error'; message.textContent = invalid ? 'Usa valores entre 0 e 100.' : 'As metas não podem somar mais de 100%.'; return; }
      try {
        const response = await fetch('/api/portfolio-targets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ targets }) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Não foi possível guardar as metas.');
        await refreshState();
      } catch (error) { message.className = 'form-message error'; message.textContent = error.message; }
    });
    $('#clear-portfolio-targets').addEventListener('click', async () => {
      const response = await fetch('/api/portfolio-targets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ targets: {} }) });
      if (response.ok) await refreshState();
    });
  }
  const rows = portfolio.positions || [];
  if (!rows.length) {
    $('#portfolio-table').innerHTML = '<tr><td colspan="7" class="table-empty">Adiciona uma posição para começar a acompanhar.</td></tr>';
    return;
  }
  $('#portfolio-table').innerHTML = rows.map((position) => { const cost = Number(position.avg_cost) > 0 ? money(position.avg_cost, position.currency) : 'não indicado'; const costNote = position.cost_basis_status === 'desconhecido' ? 'preço de compra não consta no PDF' : position.cost_basis_status === 'não indicado' ? 'confirmar na corretora' : (position.cost_unit ? `unidade ${position.cost_unit}` : 'preço médio'); const owner = [position.broker, position.sector].filter(Boolean).join(' · '); const basis = position.acquisition_analysis || {}; const result = basis.available ? `${percent(basis.pnl_pct)}<span class="position-sector">${escapeHtml(basis.level)}</span>` : '<span class="position-sector">sem comparação</span>'; const valueNote = position.valuation_approximate ? `<span class="position-sector">${escapeHtml(position.valuation_source || 'aproximado')}</span>` : ''; return `<tr><td>${escapeHtml(position.symbol)}<span class="position-sector">${escapeHtml(owner)}</span></td><td>${money(position.market_value, position.market_value_currency || 'EUR')}${valueNote}</td><td>${cost}<span class="position-sector">${escapeHtml(costNote)}</span></td><td class="${basis.available && Number(basis.pnl_pct) < 0 ? 'loss-value' : 'gain-value'}">${result}</td><td>${percent(position.weight)}</td><td><span class="action-pill ${actionClass(position.action)}">${escapeHtml(actionShort(position.action))}</span></td><td><button class="delete-position" data-delete="${escapeHtml(position.symbol)}" title="Remover ${escapeHtml(position.symbol)}" aria-label="Remover ${escapeHtml(position.symbol)}">×</button></td></tr>`; }).join('');
  $('#portfolio-table').querySelectorAll('[data-delete]').forEach((button) => button.addEventListener('click', () => removePosition(button.dataset.delete)));
}

async function savePortfolio(positions) {
  const response = await fetch('/api/portfolio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ positions }) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível guardar o inventário.');
  ui.state = result;
  renderAll();
}

async function refreshState() {
  const response = await fetch('/api/state', { cache: 'no-store' });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível atualizar o estado.');
  ui.state = result;
  renderAll();
}

async function removePosition(symbol) {
  const remaining = (ui.state.portfolio.positions || []).filter((item) => item.symbol !== symbol).map((item) => ({ ...item }));
  try { await savePortfolio(remaining); } catch (error) { window.alert(error.message); }
}

const watchRuleLabels = { score: 'score', confidence: 'confiança', momentum: 'impulso', relative_strength: 'força relativa' };
const watchScopeLabels = { all: 'todo o catálogo', favorites: 'favoritos', portfolio: 'minha carteira', sector: 'setor atual' };

function watchRuleDescription(rule) {
  return `${watchRuleLabels[rule.metric] || rule.metric} ${rule.operator === 'gte' ? '≥' : '≤'} ${score(rule.threshold)} · ${watchScopeLabels[rule.scope] || rule.scope}`;
}

function watchRuleTriggerLabel(rule) {
  return rule.trigger === 'always' ? 'cada snapshot' : 'ao entrar';
}

function watchRuleAssets(rule) {
  const signals = signalMap();
  const favorites = ui.favorites;
  const portfolioSymbols = new Set((ui.state.portfolio?.positions || []).map((item) => String(item.symbol || '').toUpperCase()));
  return (ui.state.catalog || ui.state.universe || [])
    .filter((asset) => rule.scope !== 'favorites' || favorites.has(String(asset.symbol || '').toUpperCase()))
    .filter((asset) => rule.scope !== 'portfolio' || portfolioSymbols.has(String(asset.symbol || '').toUpperCase()))
    .filter((asset) => rule.scope !== 'sector' || (ui.sector !== 'Todos' && asset.sector === ui.sector))
    .map((asset) => ({ ...asset, ...(signals.get(String(asset.symbol || '').toUpperCase()) || {}) }))
    .filter((asset) => {
      const value = Number(asset[rule.metric]);
      if (!Number.isFinite(value)) return false;
      return rule.operator === 'gte' ? value >= rule.threshold : value <= rule.threshold;
    });
}

function renderWatchRuleList() {
  const container = $('#watch-rule-list');
  if (!container) return;
  if (!ui.watchRules.length) {
    container.innerHTML = '<span class="watch-rule-empty">Ainda não há regras. Guarda uma para transformar o próximo snapshot numa lista de triagem.</span>';
    return;
  }
  container.innerHTML = ui.watchRules.map((rule) => {
    const matches = watchRuleAssets(rule);
    const symbols = matches.slice(0, 4).map((asset) => String(asset.symbol || '').toUpperCase()).join(', ');
    const overflow = matches.length > 4 ? ` +${matches.length - 4}` : '';
    return `<div class="watch-rule-row"><span><strong>${escapeHtml(watchRuleDescription(rule))}</strong><small>${escapeHtml(watchRuleTriggerLabel(rule))} · ${matches.length ? `${matches.length} ativo${matches.length === 1 ? '' : 's'} · ${escapeHtml(symbols)}${overflow}` : 'sem correspondências neste snapshot'}</small></span><button class="icon-button rule-remove" type="button" data-remove-rule="${escapeHtml(rule.id)}" aria-label="Remover regra">×</button></div>`;
  }).join('');
  container.querySelectorAll('[data-remove-rule]').forEach((button) => button.addEventListener('click', () => {
    const removedId = button.dataset.removeRule;
    ui.watchRules = ui.watchRules.filter((rule) => rule.id !== removedId);
    delete ui.watchRuleMatches[removedId];
    localStorage.setItem('radar:watch-rules', JSON.stringify(ui.watchRules));
    localStorage.setItem('radar:watch-rule-matches', JSON.stringify(ui.watchRuleMatches));
    renderAlerts();
  }));
}

function renderAlerts() {
  const classifySupervision = (item) => {
    const text = `${item.title || ''} ${item.detail || ''}`.toLowerCase();
    return text.includes('inventário') || text.includes('concentração') || text.includes('paper') || text.includes('drawdown') ? 'portfolio' : 'quality';
  };
  let items = [];
  const reviewKey = (item) => JSON.stringify([item.category || '', item.symbol || '', item.type || '', item.title || '', item.detail || '']);
  const addItem = (item) => {
    const enriched = { ...item };
    enriched.reviewKey = reviewKey(enriched);
    enriched.reviewed = ui.reviewedAlerts.has(enriched.reviewKey);
    items.push(enriched);
  };
  (ui.state.supervision || []).forEach((item) => addItem({ ...item, category: classifySupervision(item) }));
  (ui.state.alerts || []).slice(0, 6).forEach((event) => {
    const factor = event.dominant_factor ? ` · fator dominante: ${event.dominant_factor}${event.dominant_factor_delta == null ? '' : ` ${Number(event.dominant_factor_delta) >= 0 ? '+' : ''}${Number(event.dominant_factor_delta).toFixed(1)}`}` : '';
    addItem({ category: 'changes', level: 'info', symbol: event.symbol || '', type: event.type || 'mudança', title: `${event.symbol || 'Radar'} · ${event.type || 'mudança'}`, detail: `${event.from_action || '—'} → ${event.to_action || '—'}${factor}${event.reason ? ` · ${event.reason}` : ''}` });
  });
  ui.watchRules.forEach((rule) => {
    const matches = watchRuleAssets(rule);
    const previous = new Set(Array.isArray(ui.watchRuleMatches[rule.id]) ? ui.watchRuleMatches[rule.id] : []);
    const newMatches = matches.filter((asset) => !previous.has(String(asset.symbol || '').toUpperCase()));
    ui.watchRuleMatches[rule.id] = matches.map((asset) => String(asset.symbol || '').toUpperCase()).filter(Boolean);
    if (!matches.length) return;
    const symbols = matches.slice(0, 6).map((asset) => String(asset.symbol || '').toUpperCase()).join(', ');
    addItem({ category: 'rules', level: 'warning', title: `Regra local · ${watchRuleDescription(rule)}`, detail: `${watchRuleTriggerLabel(rule)} · ${matches.length} correspondência${matches.length === 1 ? '' : 's'} neste snapshot: ${symbols}${matches.length > 6 ? ` +${matches.length - 6}` : ''}.` });
    if (newMatches.length) addItem({ category: 'rules', level: 'warning', title: `Entrada na regra · ${watchRuleDescription(rule)}`, detail: `${watchRuleTriggerLabel(rule)} · ${newMatches.length} ativo${newMatches.length === 1 ? '' : 's'} entrou${newMatches.length === 1 ? '' : 'ram'} agora: ${newMatches.slice(0, 6).map((asset) => asset.symbol).join(', ')}.` });
  });
  try { localStorage.setItem('radar:watch-rule-matches', JSON.stringify(ui.watchRuleMatches)); } catch (_error) { /* local persistence is optional */ }
  const outcomeSummary = ui.state.outcomes?.summary;
  const firstOutcome = Object.entries(outcomeSummary?.by_horizon || {}).find(([, value]) => Number(value.records) > 0);
  if (firstOutcome) {
    const [horizon, value] = firstOutcome;
    const positive = value.positive_rate == null ? '—' : `${(Number(value.positive_rate) * 100).toFixed(1)}%`;
    const average = value.average_return == null ? '—' : `${(Number(value.average_return) * 100).toFixed(2)}%`;
    addItem({ category: 'evidence', level: 'info', title: `Evidência observada · ${horizon} observações`, detail: `${value.records} registos fechados · ${positive} com retorno positivo · média ${average}. Leitura descritiva, não previsão.` });
  }
  const cacheNamespaces = ui.state.cache_stats?.namespaces || {};
  const cacheTotals = Object.values(cacheNamespaces).reduce((totals, stats) => ({
    hits: totals.hits + Number(stats.hits || 0),
    misses: totals.misses + Number(stats.misses || 0),
    errors: totals.errors + Number(stats.errors || 0),
    stale: totals.stale + Number(stats.stale_fallbacks || 0),
  }), { hits: 0, misses: 0, errors: 0, stale: 0 });
  const cacheRequests = cacheTotals.hits + cacheTotals.misses + cacheTotals.errors;
  if (cacheRequests) {
    const hitRate = cacheTotals.hits / cacheRequests;
    addItem({ category: 'quality', level: hitRate >= 0.5 ? 'good' : 'info', title: `Eficiência do cache · ${(hitRate * 100).toFixed(1)}%`, detail: `${cacheTotals.hits} respostas reutilizadas · ${cacheTotals.misses} chamadas ao provider · ${cacheTotals.errors} erros · ${cacheTotals.stale} fallbacks antigos. Sem URLs ou chaves guardadas.` });
  }
  const pendingCount = items.filter((item) => !item.reviewed).length;
  const filterDefs = [['all', 'Todos'], ['unreviewed', `Por rever (${pendingCount})`], ['quality', 'Qualidade'], ['changes', 'Mudanças'], ['rules', 'Regras'], ['portfolio', 'Carteira'], ['evidence', 'Evidência'], ['reviewed', 'Revistos']];
  $('#alert-filters').innerHTML = filterDefs.map(([key, label]) => `<button class="filter-button ${ui.alertFilter === key ? 'active' : ''}" type="button" data-alert-filter="${key}">${label}</button>`).join('') + (ui.reviewedAlerts.size ? '<button class="filter-button" type="button" data-clear-reviewed>Limpar revistos</button>' : '');
  $('#alert-filters').querySelectorAll('[data-alert-filter]').forEach((button) => button.addEventListener('click', () => { ui.alertFilter = button.dataset.alertFilter; renderAlerts(); }));
  $('#alert-filters').querySelector('[data-clear-reviewed]')?.addEventListener('click', () => { ui.reviewedAlerts.clear(); localStorage.setItem('radar:reviewed-alerts', '[]'); renderAlerts(); });
  if (ui.alertFilter === 'unreviewed') items = items.filter((item) => !item.reviewed);
  else if (ui.alertFilter === 'reviewed') items = items.filter((item) => item.reviewed);
  else if (ui.alertFilter !== 'all') items = items.filter((item) => item.category === ui.alertFilter);
  if (ui.alertQuery) items = items.filter((item) => `${item.title || ''} ${item.detail || ''} ${item.symbol || ''}`.toLowerCase().includes(ui.alertQuery.toLowerCase()));
  const levelOrder = { danger: 0, warning: 1, info: 2, good: 3 };
  items.sort((left, right) => {
    if (ui.alertSort === 'severity') return (levelOrder[left.level] ?? 9) - (levelOrder[right.level] ?? 9) || Number(left.reviewed) - Number(right.reviewed);
    if (ui.alertSort === 'category') return String(left.category || '').localeCompare(String(right.category || '')) || Number(left.reviewed) - Number(right.reviewed);
    return Number(left.reviewed) - Number(right.reviewed);
  });
  ui.alertItems = items.slice();
  const reviewVisibleButton = $('#review-visible-alerts');
  if (reviewVisibleButton) {
    const pendingVisible = ui.alertItems.filter((item) => item.reviewKey && !item.reviewed).length;
    reviewVisibleButton.disabled = pendingVisible === 0;
    reviewVisibleButton.textContent = pendingVisible ? `Marcar ${pendingVisible} visíveis revistos` : 'Tudo revisto';
  }
  if (!items.length) items.push({ level: 'good', title: 'Nada nesta categoria', detail: 'Não há itens nesta categoria no último snapshot.' });
  $('#alert-list').innerHTML = items.map((item) => {
    const footer = item.reviewKey ? `<div class="alert-item-footer"><span>${item.reviewed ? 'revisto neste browser' : 'por rever'}</span><button class="review-button" type="button" data-review-alert="${escapeHtml(item.reviewKey)}">${item.reviewed ? 'Reabrir' : 'Marcar revisto'}</button></div>` : '';
    return `<article class="alert-item ${escapeHtml(item.level || 'info')} ${item.reviewed ? 'is-reviewed' : ''}"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.detail)}</p>${footer}</article>`;
  }).join('');
  $('#alert-list').querySelectorAll('[data-review-alert]').forEach((button) => button.addEventListener('click', () => {
    const key = button.dataset.reviewAlert;
    if (ui.reviewedAlerts.has(key)) ui.reviewedAlerts.delete(key);
    else ui.reviewedAlerts.add(key);
    localStorage.setItem('radar:reviewed-alerts', JSON.stringify([...ui.reviewedAlerts].slice(-300)));
    renderAlerts();
  }));
  renderWatchRuleList();
  renderNotificationSettings();
}

function reviewVisibleAlerts() {
  const visible = (ui.alertItems || []).filter((item) => item.reviewKey && !item.reviewed);
  if (!visible.length) return;
  visible.forEach((item) => ui.reviewedAlerts.add(item.reviewKey));
  localStorage.setItem('radar:reviewed-alerts', JSON.stringify([...ui.reviewedAlerts].slice(-300)));
  renderAlerts();
}

function renderNotificationSettings() {
  const status = $('#notification-status');
  const button = $('#enable-notifications');
  if (!status || !button) return;
  if (typeof Notification === 'undefined' || typeof Notification.requestPermission !== 'function') {
    status.textContent = 'não suportadas neste browser';
    button.disabled = true;
    button.textContent = 'Indisponível';
    return;
  }
  if (Notification.permission === 'denied') {
    status.textContent = 'bloqueadas nas permissões do browser';
    button.disabled = true;
    button.textContent = 'Bloqueadas';
    return;
  }
  if (ui.notificationsEnabled && Notification.permission === 'granted') {
    status.textContent = 'ativas · só quando chega um snapshot novo';
    button.disabled = false;
    button.textContent = 'Desativar';
    return;
  }
  status.textContent = 'desativadas · não há chamadas externas';
  button.disabled = false;
  button.textContent = 'Ativar notificações';
}

function renderReportLibraryLegacy() {
  const container = $('#report-library');
  if (!container) return;
  const sensitivity = ui.state.sensitivity || {};
  const liveValidation = ui.state.live_validation || {};
  const validationRow = liveValidation.available
    ? `<article class="report-library-row"><div><strong>Validação live · ${liveValidation.passed ? 'passou' : 'falhou'}</strong><small>${Number(liveValidation.rows || 0)} linhas verificadas · ${Number(liveValidation.critical_failures || 0)} falhas críticas · ${Number(liveValidation.context_failures || 0)} contexto · sem chamadas ao abrir</small></div><span class="report-library-actions"><a class="secondary-button" href="/api/live-validation-report">Markdown ↓</a></span></article>`
    : '';
  const sensitivityRow = sensitivity.available
    ? `<article class="report-library-row"><div><strong>Estudo de sensibilidade</strong><small>${Number(sensitivity.scenario_count || 0)} cenários · diagnóstico de fragilidade · sem chamadas ao abrir</small></div><span class="report-library-actions"><a class="secondary-button" href="${escapeHtml(sensitivity.url || '/api/sensitivity-report')}">Abrir relatório <span aria-hidden="true">↓</span></a></span></article>`
    : '';
  const reports = ui.state.report_library || [];
  if (!reports.length && !sensitivity.available && !liveValidation.available) {
    container.innerHTML = '<p class="report-library-empty">Ainda não há cópias arquivadas. A próxima execução diária cria o primeiro relatório.</p>';
    return;
  }
  container.innerHTML = validationRow + sensitivityRow + reports.map((item) => `<article class="report-library-row"><div><strong>Snapshot ${escapeHtml(item.as_of)}</strong><small>gerado localmente · sem chamadas ao abrir</small></div><span class="report-library-actions"><a class="report-library-link" href="${escapeHtml(item.markdown)}">Abrir texto <span aria-hidden="true">↓</span></a>${item.pdf ? `<a class="report-library-link" href="${escapeHtml(item.pdf)}">Abrir PDF <span aria-hidden="true">↓</span></a>` : ''}</span></article>`).join('');
}

function renderReportLibrary() {
  const container = $('#report-library');
  if (!container) return;
  const sensitivity = ui.state.sensitivity || {};
  const liveValidation = ui.state.live_validation || {};
  const link = (href, label) => `<a class="report-library-link" href="${escapeHtml(href)}">${escapeHtml(label)} <span aria-hidden="true">↓</span></a>`;
  const validationRow = liveValidation.available
    ? `<article class="report-library-row"><div><strong>Validação live · ${liveValidation.passed ? 'passou' : 'falhou'}</strong><small>${Number(liveValidation.rows || 0).toLocaleString('pt-PT')} linhas verificadas · ${Number(liveValidation.critical_failures || 0)} falhas críticas · ${Number(liveValidation.context_failures || 0)} falhas de contexto · abre sem chamadas</small></div><span class="report-library-actions">${link('/api/live-validation-report', 'Abrir report')}</span></article>`
    : '';
  const sensitivityRow = sensitivity.available
    ? `<article class="report-library-row"><div><strong>Estudo de sensibilidade</strong><small>${Number(sensitivity.scenario_count || 0)} cenários de demonstração · diagnóstico de fragilidade · abre sem chamadas</small></div><span class="report-library-actions">${link(sensitivity.url || '/api/sensitivity-report', 'Abrir report')}</span></article>`
    : '';
  const reports = ui.state.report_library || [];
  if (!reports.length && !sensitivity.available && !liveValidation.available) {
    container.innerHTML = '<p class="report-library-empty">Ainda não há cópias arquivadas. A próxima execução diária cria o primeiro report.</p>';
    return;
  }
  container.innerHTML = validationRow + sensitivityRow + reports.map((item) => `<article class="report-library-row"><div><strong>Snapshot ${escapeHtml(item.as_of)}</strong><small>cópia local pronta a abrir · sem chamadas ao abrir</small></div><span class="report-library-actions">${link(item.markdown, 'Abrir texto')}${item.pdf ? link(item.pdf, 'Abrir PDF') : ''}</span></article>`).join('');
}

function renderPaperTrading() {
  const container = $('#paper-report-panel');
  if (!container) return;
  const paper = ui.state.paper || {};
  const progress = paper.review_progress || {};
  const coverage = progress.coverage || {};
  if (!Object.keys(paper).length) {
    container.innerHTML = '<div class="paper-empty">Ainda não existe um ledger de paper trading. A próxima execução válida poderá iniciar a amostra.</div>';
    return;
  }
  const initialCash = Number(paper.initial_cash);
  const equity = Number(paper.equity);
  const returnValue = Number.isFinite(initialCash) && initialCash > 0 && Number.isFinite(equity) ? equity / initialCash - 1 : NaN;
  const snapshots = Number(progress.snapshots || 0);
  const targetSnapshots = Math.max(1, Number(progress.target_snapshots || 1));
  const decisions = Number(progress.decision_records || 0);
  const targetDecisions = Math.max(1, Number(progress.target_decisions || 1));
  const snapshotPct = Math.min(100, Math.max(0, snapshots / targetSnapshots * 100));
  const decisionPct = Math.min(100, Math.max(0, decisions / targetDecisions * 100));
  const ready = Boolean(progress.ready_for_review);
  const risk = paper.last_risk_control || {};
  const entryReview = paper.last_entry_review || {};
  const entryBlockers = Array.isArray(entryReview.blockers) ? entryReview.blockers : [];
  const entryCandidates = Array.isArray(entryReview.buy_candidates) ? entryReview.buy_candidates : [];
  const nearEntryCandidates = Array.isArray(entryReview.near_entry_candidates) ? entryReview.near_entry_candidates : [];
  const entrySummary = entryCandidates.length ? `candidatos: ${entryCandidates.join(', ')}` : 'nenhum candidato a compra neste snapshot';
  const nearEntrySummary = nearEntryCandidates.length ? `em observação: ${nearEntryCandidates.map((item) => `${item.symbol} (${Number(item.score || 0).toFixed(1)}; faltam ${Number(item.gap_to_buy ?? 0).toFixed(1)}; vigiar ${(item.watch_factors || []).join(', ') || 'fatores do score'})`).join(', ')}` : 'sem candidato próximo do limiar';
  const entryMessages = entryBlockers.map((item) => item && item.message).filter(Boolean).slice(0, 2);
  const duplicate = entryReview.status === 'duplicate';
  const statusLabel = ready ? 'pronto para revisão' : duplicate ? 'sem nova ronda' : 'em validação';
  const statusClass = ready ? 'paper-ready' : 'paper-progress';
  const trades = Number(paper.total_trades || 0);
  const coverageSummary = coverage.available ? `${Number(coverage.observed_snapshots || 0)}/${Number(coverage.potential_weekdays || 0)} dias úteis potenciais (${Number(coverage.coverage_pct || 0).toFixed(1)}%)` : 'ainda sem base temporal';
  const missingCoverage = Array.isArray(coverage.missing_potential_dates) && coverage.missing_potential_dates.length ? `Sem snapshot: ${coverage.missing_potential_dates.slice(0, 5).join(', ')}${coverage.missing_potential_dates.length > 5 ? '…' : ''}.` : 'Não há lacunas entre snapshots observados.';
  const noTradeCopy = trades === 0 ? 'Ainda não houve uma execução simulada; isto não é um resultado positivo nem negativo.' : `${trades} operação${trades === 1 ? '' : 'ões'} simulada${trades === 1 ? '' : 's'} no ledger.`;
  const ladderPaper = ui.state.paper_ladder || {};
  const ladderReview = ladderPaper.last_entry_review || {};
  const ladderConfig = ladderPaper.entry_ladder || {};
  const ladderTiers = Array.isArray(ladderConfig.tiers) ? ladderConfig.tiers : [];
  const ladderCandidates = Array.isArray(ladderReview.ladder_candidates) ? ladderReview.ladder_candidates : [];
  const ladderRows = ladderTiers.map((tier) => {
    const min = Number(tier.min_score || 0).toFixed(0);
    const max = Number(tier.max_score || 0) >= 101 ? '100+' : Number(tier.max_score || 0).toFixed(0);
    const amount = Number(tier.allocation_pct || 0) * Number(ladderPaper.initial_cash || 100000);
    return `<div class="ladder-tier"><span class="tier-name">${escapeHtml(tier.name || 'nível')}</span><strong>${min}–${max}</strong><span>${money(amount)} · ${Number(tier.horizon_days || 0)} sessões</span></div>`;
  }).join('');
  const ladderMarkup = Object.keys(ladderPaper).length ? `<section class="paper-ladder-card"><div class="paper-ladder-head"><div><span class="card-label"><span class="label-dot blue"></span>escada experimental · paper-ladder-v1</span><strong>Entradas graduais por score</strong><small>Ledger separado; não altera o teste principal nem envia ordens.</small></div><span class="paper-status paper-progress">${Number(ladderPaper.total_trades || 0)} operações</span></div><div class="ladder-grid">${ladderRows || '<small>Configuração da escada ainda não disponível.</small>'}</div><div class="paper-ladder-note"><strong>${ladderCandidates.length ? `${ladderCandidates.length} candidato(s) elegível(eis)` : 'Sem candidato elegível nesta ronda'}</strong><span>Score mínimo 60 · confiança de dados mínima ${Number(ladderConfig.min_confidence || 70).toFixed(0)} · máximo 2 entradas por sessão.</span></div><div class="paper-report-foot"><span>O montante final é limitado por volatilidade, caixa, setor e exposição total.</span><span class="paper-report-actions"><a class="report-library-link" href="/api/paper-report?policy=ladder&format=md">Abrir report <span aria-hidden="true">↓</span></a><a class="report-library-link" href="/api/paper-report?policy=ladder&format=csv">Exportar trades <span aria-hidden="true">↓</span></a></span></div></section>` : '';
  const matrixPaper = ui.state.paper_matrix || {};
  const matrixConfig = matrixPaper.entry_matrix || {};
  const matrixReview = matrixPaper.last_entry_review || {};
  const matrixHorizons = Array.isArray(matrixConfig.horizons) ? matrixConfig.horizons : [];
  const matrixCandidates = Array.isArray(matrixReview.candidates) ? matrixReview.candidates : [];
  const matrixRows = matrixHorizons.map((horizon) => `<div class="matrix-horizon"><strong>${escapeHtml(horizon.label || horizon.key || 'prazo')}</strong><span>${Number(horizon.sessions || 0)} sessões</span><div>${(horizon.tiers || []).map((tier) => `<span class="matrix-cell"><b>${escapeHtml(tier.name || 'score')}</b><em>${(Number(tier.allocation_pct || 0) * 100).toFixed(2)}%</em></span>`).join('')}</div></div>`).join('');
  const matrixMarkup = Object.keys(matrixPaper).length ? `<section class="paper-matrix-card"><div class="paper-ladder-head"><div><span class="card-label"><span class="label-dot teal"></span>matriz experimental · paper-matrix-v2</span><strong>Score diferente, prazo diferente</strong><small>Ledger separado; o mesmo ativo pode ter um slot por prazo, com risco agregado.</small></div><span class="paper-status paper-progress">${Number(matrixPaper.total_trades || 0)} operações</span></div><div class="matrix-grid">${matrixRows || '<small>Configuração da matriz ainda não disponível.</small>'}</div><div class="paper-ladder-note"><strong>${matrixCandidates.length ? `${matrixCandidates.length} célula(s) elegível(eis)` : 'Sem célula elegível nesta ronda'}</strong><span>Entrada a partir de ${Number(matrixConfig.min_entry_score || 60).toFixed(0)} · saída abaixo de ${Number(matrixConfig.exit_score || 45).toFixed(0)} ou na maturidade · máximo ${Number(matrixConfig.max_new_entries || 2)} entradas por sessão.</span></div><div class="paper-report-foot"><span>Limites agregados: ativo ${(Number(matrixConfig.max_asset_pct || 0) * 100).toFixed(0)}% · setor ${(Number(matrixConfig.max_sector_pct || 0) * 100).toFixed(0)}% · total ${(Number(matrixConfig.max_total_exposure_pct || 0) * 100).toFixed(0)}%.</span><span class="paper-report-actions"><a class="report-library-link" href="/api/paper-report?policy=matrix&format=md">Abrir report <span aria-hidden="true">↓</span></a><a class="report-library-link" href="/api/paper-report?policy=matrix&format=csv">Exportar trades <span aria-hidden="true">↓</span></a></span></div></section>` : '';
  container.innerHTML = `
    <div class="paper-report-head">
      <div><span class="card-label"><span class="label-dot orange"></span>paper trading · $100k</span><strong>Teste sem ordens reais</strong><small>${escapeHtml(paper.paper_only ? 'Os dados são fictícios e ficam apenas no computador.' : 'Confirma o modo antes de interpretar este resultado.')}</small></div>
      <span class="paper-status ${statusClass}">${statusLabel}</span>
    </div>
    <div class="paper-metrics">
      <div><span>equity</span><strong>${money(equity)}</strong><small class="${returnValue >= 0 ? 'positive' : 'negative'}">${percent(returnValue)} desde o início</small></div>
      <div><span>cash</span><strong>${money(paper.cash)}</strong><small>${Number(paper.positions || 0)} posições</small></div>
      <div><span>amostra</span><strong>${snapshots}/${targetSnapshots}</strong><small>${decisions}/${targetDecisions} decisões</small></div>
      <div><span>último snapshot</span><strong>${escapeHtml(paper.as_of || '—')}</strong><small>${escapeHtml(paper.mode || 'sem modo')} · ${escapeHtml(noTradeCopy)}</small></div>
    </div>
    <div class="paper-progress-grid">
      <div><div class="paper-progress-label"><span>snapshots</span><b>${snapshotPct.toFixed(0)}%</b></div><div class="paper-progress-bar"><span style="width:${snapshotPct}%"></span></div></div>
      <div><div class="paper-progress-label"><span>decisões</span><b>${decisionPct.toFixed(0)}%</b></div><div class="paper-progress-bar"><span style="width:${decisionPct}%"></span></div></div>
    </div>
    <div class="paper-coverage"><div><span>cobertura operacional</span><strong>${escapeHtml(coverageSummary)}</strong></div><small>${escapeHtml(missingCoverage)} ${escapeHtml(coverage.note || 'Dias úteis potenciais; confirma feriados e fechos antes de concluir que houve uma falha.')}</small></div>
    <div class="paper-entry-review"><div><span>revisão de entradas</span><strong>${escapeHtml(entrySummary)}</strong><small>${escapeHtml(nearEntrySummary)} · ${Number(entryReview.entries || 0)} entrada(s) executada(s) · ${escapeHtml(entryReview.status || 'sem diagnóstico')}</small></div>${entryMessages.length ? `<ul>${entryMessages.map((message) => `<li>${escapeHtml(message)}</li>`).join('')}</ul>` : '<small>O ledger registará explicitamente quando o bloqueio vier de dados, sinal, risco ou alocação.</small>'}</div>
    <div class="paper-report-foot"><span>${escapeHtml(progress.message || 'A amostra está a crescer.')} ${risk.active ? 'Travão de drawdown ativo.' : 'Travão de drawdown inativo.'}</span><span class="paper-report-actions"><a class="report-library-link" href="/api/paper-report?format=md">Abrir report <span aria-hidden="true">↓</span></a><a class="report-library-link" href="/api/paper-report?format=csv">Exportar trades <span aria-hidden="true">↓</span></a></span></div>${ladderMarkup}${matrixMarkup}`;
}

function renderSnapshotComparisonLegacy() {
  const container = $('#snapshot-comparison');
  if (!container) return;
  const comparison = ui.state.snapshot_comparison || {};
  if (!comparison.available) {
    container.innerHTML = `<p class="snapshot-comparison-empty">${escapeHtml(comparison.message || 'A comparação aparece quando existirem dois snapshots em datas diferentes.')}</p>`;
    return;
  }
  const sign = Number(comparison.average_score_delta) >= 0 ? '+' : '';
  const rows = (comparison.rows || []).map((item) => {
    const delta = Number(item.score_delta || 0);
    const deltaSign = delta >= 0 ? '+' : '';
    return `<span class="comparison-row"><strong>${escapeHtml(item.symbol)}</strong><span>${Number(item.score_before).toFixed(1)} → ${Number(item.score_after).toFixed(1)}</span><b class="${delta >= 0 ? 'positive' : 'negative'}">${deltaSign}${delta.toFixed(1)}</b></span>`;
  }).join('');
  container.innerHTML = `<div class="snapshot-comparison-head"><div><span class="card-label"><span class="label-dot blue"></span>comparação local</span><small>${escapeHtml(comparison.previous_as_of)} → ${escapeHtml(comparison.current_as_of)}</small></div><span class="comparison-summary">média ${sign}${Number(comparison.average_score_delta).toFixed(1)} · ${comparison.action_changes} mudança${comparison.action_changes === 1 ? '' : 's'} de ação</span><a class="report-library-link comparison-report-link" href="/api/snapshot-comparison-report">Abrir comparação <span aria-hidden="true">↓</span></a></div><div class="comparison-grid">${rows || '<span class="snapshot-comparison-empty">Sem símbolos comuns entre os dois snapshots.</span>'}</div>`;
}

function renderSnapshotComparison() {
  const container = $('#snapshot-comparison');
  if (!container) return;
  const comparison = ui.state.snapshot_comparison || {};
  if (!comparison.available) {
    container.innerHTML = `<p class="snapshot-comparison-empty">${escapeHtml(comparison.message || 'A comparação aparece quando existirem dois snapshots em datas diferentes.')}</p>`;
    return;
  }
  const sign = Number(comparison.average_score_delta) >= 0 ? '+' : '';
  const rows = (comparison.rows || []).map((item) => {
    const delta = Number(item.score_delta || 0);
    const deltaSign = delta >= 0 ? '+' : '';
    return `<span class="comparison-row"><strong>${escapeHtml(item.symbol)}</strong><span>${Number(item.score_before).toFixed(1)} → ${Number(item.score_after).toFixed(1)}</span><b class="${delta >= 0 ? 'positive' : 'negative'}">${deltaSign}${delta.toFixed(1)}</b></span>`;
  }).join('');
  container.innerHTML = `<div class="snapshot-comparison-head"><div><span class="card-label"><span class="label-dot blue"></span>comparação local</span><small>${escapeHtml(comparison.previous_as_of)} → ${escapeHtml(comparison.current_as_of)}</small></div><span class="comparison-summary">média ${sign}${Number(comparison.average_score_delta).toFixed(1)} · ${comparison.action_changes} mudança${comparison.action_changes === 1 ? '' : 's'} de ação</span><a class="report-library-link comparison-report-link" href="/api/snapshot-comparison-report">Abrir report <span aria-hidden="true">↓</span></a></div><div class="comparison-grid">${rows || '<span class="snapshot-comparison-empty">Sem símbolos comuns entre os dois snapshots.</span>'}</div>`;
}

async function toggleLocalNotifications() {
  if (typeof Notification === 'undefined' || typeof Notification.requestPermission !== 'function') return;
  if (ui.notificationsEnabled && Notification.permission === 'granted') {
    ui.notificationsEnabled = false;
    localStorage.setItem('radar:local-notifications', 'off');
    renderNotificationSettings();
    return;
  }
  const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
  ui.notificationsEnabled = permission === 'granted';
  localStorage.setItem('radar:local-notifications', ui.notificationsEnabled ? 'on' : 'off');
  renderNotificationSettings();
}

function notifyForNewSnapshot(state) {
  const snapshotKey = `${state.meta?.as_of || ''}|${state.meta?.generated_at || ''}`;
  let previousKey = '';
  try {
    previousKey = localStorage.getItem('radar:last-notified-snapshot') || '';
    localStorage.setItem('radar:last-notified-snapshot', snapshotKey);
  } catch (_error) {
    return;
  }
  if (!ui.notificationsEnabled || typeof Notification === 'undefined' || Notification.permission !== 'granted' || !previousKey || previousKey === snapshotKey) return;
  const items = [];
  (state.alerts || []).slice(0, 6).forEach((event) => items.push({
    title: `${event.symbol || 'Radar'} · mudança`,
    body: `${event.from_action || '—'} → ${event.to_action || '—'}${event.reason ? ` · ${event.reason}` : ''}`,
  }));
  ui.watchRules.forEach((rule) => {
    const matches = watchRuleAssets(rule);
    const previous = new Set(Array.isArray(ui.watchRuleMatches[rule.id]) ? ui.watchRuleMatches[rule.id] : []);
    const eligible = rule.trigger === 'always' ? matches : matches.filter((asset) => !previous.has(String(asset.symbol || '').toUpperCase()));
    if (eligible.length) items.push({
      title: 'Regra local atingida',
      body: `${watchRuleDescription(rule)} · ${eligible.slice(0, 4).map((item) => item.symbol).join(', ')}`,
    });
  });
  items.slice(0, 5).forEach((item, index) => {
    try {
      new Notification(item.title, { body: item.body, tag: `radar-${snapshotKey}-${index}` });
    } catch (_error) {
      // Notification failures must never interrupt rendering or refresh.
    }
  });
}

function renderAll() {
  renderFreshness();
  renderSummary();
  renderDecisionBrief();
  renderFilters();
  renderSectorPulse();
  renderSectorHeatmap();
  renderSectorRotation();
  renderAssets();
  renderPortfolioFocus();
  renderPortfolio();
  renderAlerts();
  renderReportLibrary();
  renderPaperTrading();
  renderSnapshotComparison();
}

async function loadState() {
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (!response.ok) throw new Error('Não foi possível carregar os dados do radar.');
  ui.state = await response.json();
  notifyForNewSnapshot(ui.state);
  renderAll();
}

function updateAssetSearch(value) {
  ui.query = String(value || '').trim();
  const legacySearch = $('#asset-search');
  const primarySearch = $('#asset-search-primary');
  if (legacySearch && legacySearch.value !== ui.query) legacySearch.value = ui.query;
  if (primarySearch && primarySearch.value !== ui.query) primarySearch.value = ui.query;
  renderAssets();
}
$('#asset-search').addEventListener('input', (event) => updateAssetSearch(event.target.value));
$('#asset-search-primary').addEventListener('input', (event) => updateAssetSearch(event.target.value));
$('#advanced-explorer').addEventListener('toggle', () => renderAssets());
$('#saved-views').addEventListener('change', (event) => applySavedView(event.target.value));
$('#asset-sort').addEventListener('change', (event) => { ui.assetSort = event.target.value; renderAssets(); });
$('#save-view').addEventListener('click', saveCurrentView);
$('#remove-view').addEventListener('click', removeSelectedView);
$('#export-assets-csv').addEventListener('click', exportFilteredAssetsCsv);
$('#export-portfolio-report').addEventListener('click', exportPortfolioReport);
$('#watch-rule-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const rule = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    metric: $('#rule-metric').value,
    operator: $('#rule-operator').value,
    threshold: Number($('#rule-threshold').value),
    scope: $('#rule-scope').value,
    trigger: $('#rule-trigger').value === 'always' ? 'always' : 'enter',
  };
  if (!Number.isFinite(rule.threshold)) return;
  ui.watchRules = [rule, ...ui.watchRules.filter((item) => !(item.metric === rule.metric && item.operator === rule.operator && item.threshold === rule.threshold && item.scope === rule.scope))].slice(0, 20);
  localStorage.setItem('radar:watch-rules', JSON.stringify(ui.watchRules));
  renderAlerts();
});
$('#clear-compare').addEventListener('click', () => { ui.compareSymbols = []; renderAssets(); });
$('#enable-notifications').addEventListener('click', () => { toggleLocalNotifications().catch(() => {}); });
$('#alert-search').addEventListener('input', (event) => { ui.alertQuery = event.target.value.trim(); renderAlerts(); });
$('#alert-sort').addEventListener('change', (event) => { ui.alertSort = event.target.value; renderAlerts(); });
$('#export-alerts-report').addEventListener('click', exportAlertsReport);
$('#review-visible-alerts').addEventListener('click', reviewVisibleAlerts);
$('#refresh-button').addEventListener('click', async () => {
  $('#refresh-button').disabled = true;
  try { await loadState(); } catch (error) { window.alert(error.message); }
  $('#refresh-button').disabled = false;
});
$('#logout-button')?.addEventListener('click', async () => {
  try { await fetch('/api/logout', { method: 'POST' }); } finally { window.location.href = '/login'; }
});
$('#position-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = $('#form-message');
  const symbol = $('#position-symbol').value.trim().toUpperCase();
  const position = { symbol, quantity: Number($('#position-quantity').value), avg_cost: Number($('#position-cost').value), currency: 'USD' };
  const existing = (ui.state.portfolio.positions || []).filter((item) => item.symbol !== symbol).map((item) => ({ ...item }));
  try { await savePortfolio([...existing, position]); event.target.reset(); message.className = 'form-message good'; message.textContent = 'Posição guardada.'; } catch (error) { message.className = 'form-message error'; message.textContent = error.message; }
});
document.addEventListener('keydown', (event) => { if (event.key === '/' && document.activeElement.tagName !== 'INPUT') { event.preventDefault(); $('#asset-search-primary').focus(); } });
loadState().catch((error) => { $('#freshness').innerHTML = `<span class="status-dot" style="background:var(--red)"></span><span>${escapeHtml(error.message)}</span>`; });
setInterval(() => { loadState().catch(() => {}); }, 60_000);
