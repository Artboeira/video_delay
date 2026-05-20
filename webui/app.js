// ─────────────────────────────────────────────────────────────────
// Video Delay — config UI controller
// Conversa com o app Python via /api/{config,status,monitors,shutdown}.
// ───────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const STATE = {
  config: null,    // último estado servido pelo backend
  monitors: [],    // lista enumerada
  dirty: false,    // mudou desde o último save
};

// ──────────────────────────────────────────────────────────────────
//  Formatação
// ──────────────────────────────────────────────────────────────────
function formatDelay(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}min ${String(s).padStart(2, '0')}s`;
}

function toast(msg, kind = 'ok') {
  const el = $('toast');
  el.textContent = msg;
  el.dataset.kind = kind;
  el.classList.add('is-visible');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('is-visible'), 2200);
}

// ──────────────────────────────────────────────────────────────────
//  Render
// ──────────────────────────────────────────────────────────────────
function renderMonitors(selected) {
  const root = $('monitor-list');
  root.innerHTML = '';
  for (const m of STATE.monitors) {
    const label = document.createElement('label');
    label.className = 'monitor-card' + (m.index === selected ? ' is-selected' : '');
    label.innerHTML = `
      <span class="monitor-card__index">Índice ${m.index}${m.primary ? ' · primário' : ''}</span>
      <span class="monitor-card__name">${m.name || `Monitor ${m.index}`}</span>
      <span class="monitor-card__meta">${m.width && m.height ? `${m.width}×${m.height}` : '—'}</span>
      <input type="radio" name="monitor" value="${m.index}" ${m.index === selected ? 'checked' : ''} />
    `;
    label.addEventListener('click', () => {
      STATE.config.mpv_fullscreen_monitor = m.index;
      STATE.dirty = true;
      renderMonitors(m.index);
    });
    root.appendChild(label);
  }
}

function fillForm(c) {
  $('delay-range').value = c.delay_seconds;
  $('delay-readout').textContent = formatDelay(c.delay_seconds);
  $('delay-readout-raw').textContent = `${c.delay_seconds} segundos`;
  $('capture-device').value = c.capture_device || '';
  $('test-mode').checked = !!c.test_mode;
  $('windowed-mode').checked = !!c.windowed_mode;
  $('preset').value = c.video_quality?.preset || 'ultrafast';
  $('crf').value = c.video_quality?.crf ?? 18;
  $('segment-duration').value = c.segment_duration ?? 5;
  $('max-age').value = c.max_segment_age_seconds ?? 240;
  renderMonitors(c.mpv_fullscreen_monitor ?? 0);
}

function readForm() {
  return {
    delay_seconds:           parseInt($('delay-range').value, 10),
    capture_device:          $('capture-device').value.trim(),
    test_mode:               $('test-mode').checked,
    windowed_mode:           $('windowed-mode').checked,
    segment_duration:        parseInt($('segment-duration').value, 10),
    max_segment_age_seconds: parseInt($('max-age').value, 10),
    mpv_fullscreen_monitor:  STATE.config.mpv_fullscreen_monitor ?? 0,
    video_quality: {
      preset: $('preset').value,
      crf:    parseInt($('crf').value, 10),
    },
  };
}

// ──────────────────────────────────────────────────────────────────
//  Status
// ──────────────────────────────────────────────────────────────────
function applyStatus(s) {
  $('st-capture').textContent = s.capture_running ? '● ATIVO' : '○ INATIVO';
  $('st-capture').style.color = s.capture_running ? 'var(--ab-moss)' : 'var(--ab-fg-muted)';
  $('st-player').textContent = s.player_status || '—';
  $('st-cleaned').textContent = String(s.deleted_count ?? 0);
  $('st-buffer').textContent = `${Math.round((s.buffer_progress ?? 0) * 100)}%`;
  $('st-buffer-fill').style.width = `${Math.min(100, Math.round((s.buffer_progress ?? 0) * 100))}%`;

  const badge = $('hero-state');
  if (s.capture_running && s.player_playing) {
    badge.dataset.state = 'ok';
    badge.textContent = 'Em operação';
  } else if (s.capture_running) {
    badge.dataset.state = 'warn';
    badge.textContent = 'Aquecendo buffer';
  } else {
    badge.dataset.state = 'err';
    badge.textContent = s.capture_error?.slice(0, 30) || 'Sem captura';
  }
}

// ──────────────────────────────────────────────────────────────────
//  Networking
// ──────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function loadAll() {
  const [config, monitors, status] = await Promise.all([
    api('/api/config'),
    api('/api/monitors'),
    api('/api/status'),
  ]);
  STATE.config = config;
  STATE.monitors = monitors;
  STATE.dirty = false;
  fillForm(config);
  applyStatus(status);
}

async function save() {
  const payload = readForm();
  // Coerência mínima feita no cliente; backend valida de novo.
  if (payload.max_segment_age_seconds < payload.delay_seconds + 60) {
    toast('Idade máx. deve ser pelo menos 60s acima do delay', 'err');
    return;
  }
  try {
    const r = await api('/api/config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    STATE.config = r;
    STATE.dirty = false;
    toast('Configuração aplicada');
  } catch (e) {
    toast('Falha ao salvar', 'err');
  }
}

async function pollStatus() {
  try {
    const s = await api('/api/status');
    applyStatus(s);
  } catch {
    $('hero-state').dataset.state = 'err';
    $('hero-state').textContent = 'Desconectado';
  } finally {
    setTimeout(pollStatus, 1000);
  }
}

// ──────────────────────────────────────────────────────────────────
//  Wizard — first-run guided setup
// ──────────────────────────────────────────────────────────────────
const WIZARD = {
  step: 1,
  total: 4,
  device: null,   // {index, name, platform_id}
  testMode: false,
  monitor: 0,
  delay: 120,
};

function showWizard() {
  document.getElementById('wizard').hidden = false;
  document.getElementById('dashboard').hidden = true;
}

function showDashboard() {
  document.getElementById('wizard').hidden = true;
  document.getElementById('dashboard').hidden = false;
}

function renderWizardStep() {
  document.querySelectorAll('.wizard__step').forEach(el => {
    el.classList.toggle('is-active', parseInt(el.dataset.step, 10) === WIZARD.step);
  });
  document.querySelectorAll('.wizard__step-pip').forEach(el => {
    const n = parseInt(el.dataset.step, 10);
    el.classList.toggle('is-active', n === WIZARD.step);
    el.classList.toggle('is-done', n < WIZARD.step);
  });
}

function wizardNext() {
  if (WIZARD.step < WIZARD.total) {
    WIZARD.step += 1;
    renderWizardStep();
  }
}

function wizardBack() {
  if (WIZARD.step > 1) {
    WIZARD.step -= 1;
    renderWizardStep();
  }
}

async function loadWizardData() {
  const [devices, monitors] = await Promise.all([
    api('/api/capture-devices'),
    api('/api/monitors'),
  ]);

  // Step 2: device cards
  const dList = $('wizard-device-list');
  dList.innerHTML = '';
  if (devices.length === 0) {
    dList.innerHTML = '<p class="field__hint">Nenhuma placa detectada. Ative o modo de teste abaixo para continuar.</p>';
  }
  for (const d of devices) {
    const card = document.createElement('label');
    card.className = 'monitor-card';
    card.innerHTML = `
      <span class="monitor-card__index">Dispositivo ${d.index}</span>
      <span class="monitor-card__name">${d.name}</span>
      <span class="monitor-card__meta">ID: ${d.platform_id}</span>
      <input type="radio" name="wizard-device" value="${d.platform_id}" />
    `;
    card.addEventListener('click', () => {
      WIZARD.device = d;
      WIZARD.testMode = false;
      $('wizard-test-mode').checked = false;
      [...dList.querySelectorAll('.monitor-card')].forEach(c =>
        c.classList.remove('is-selected'));
      card.classList.add('is-selected');
    });
    dList.appendChild(card);
  }

  // Step 3: monitor cards
  const mList = $('wizard-monitor-list');
  mList.innerHTML = '';
  for (const m of monitors) {
    const card = document.createElement('label');
    card.className = 'monitor-card' + (m.index === WIZARD.monitor ? ' is-selected' : '');
    card.innerHTML = `
      <span class="monitor-card__index">Índice ${m.index}${m.primary ? ' · primário' : ''}</span>
      <span class="monitor-card__name">${m.name || 'Monitor ' + m.index}</span>
      <span class="monitor-card__meta">${m.width && m.height ? `${m.width}×${m.height}` : '—'}</span>
    `;
    card.addEventListener('click', () => {
      WIZARD.monitor = m.index;
      [...mList.querySelectorAll('.monitor-card')].forEach(c =>
        c.classList.remove('is-selected'));
      card.classList.add('is-selected');
    });
    mList.appendChild(card);
  }
}

async function wizardFinish() {
  // Decide payload final
  if (!WIZARD.testMode && !WIZARD.device) {
    toast('Selecione uma placa ou ative modo de teste', 'err');
    WIZARD.step = 2;
    renderWizardStep();
    return;
  }

  const payload = {
    delay_seconds: WIZARD.delay,
    test_mode: WIZARD.testMode,
    capture_device: WIZARD.testMode
      ? 'YOUR_CAPTURE_CARD_NAME'
      : WIZARD.device.platform_id,
    mpv_fullscreen_monitor: WIZARD.monitor,
  };

  try {
    await api('/api/setup-complete', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Sistema iniciado');
    await loadAll();
    showDashboard();
    pollStatus();
  } catch (e) {
    toast('Falha ao iniciar: ' + e.message, 'err');
  }
}

function wireWizard() {
  document.querySelectorAll('[data-action="next"]').forEach(b => {
    b.addEventListener('click', wizardNext);
  });
  document.querySelectorAll('[data-action="back"]').forEach(b => {
    b.addEventListener('click', wizardBack);
  });

  $('wizard-test-mode').addEventListener('change', (e) => {
    WIZARD.testMode = e.target.checked;
    if (WIZARD.testMode) {
      // Limpa seleção de placa quando ativa test mode
      [...$('wizard-device-list').querySelectorAll('.monitor-card')].forEach(c =>
        c.classList.remove('is-selected'));
      WIZARD.device = null;
    }
  });

  $('wizard-delay').addEventListener('input', (e) => {
    WIZARD.delay = parseInt(e.target.value, 10);
    $('wizard-delay-readout').textContent = formatDelay(WIZARD.delay);
    $('wizard-delay-raw').textContent = `${WIZARD.delay} segundos`;
  });

  $('wizard-finish').addEventListener('click', wizardFinish);
}


// ──────────────────────────────────────────────────────────────────
//  Wiring
// ──────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  $('footer-host').textContent = location.host || 'localhost';

  $('delay-range').addEventListener('input', (e) => {
    const v = parseInt(e.target.value, 10);
    $('delay-readout').textContent = formatDelay(v);
    $('delay-readout-raw').textContent = `${v} segundos`;
    STATE.dirty = true;
  });

  ['capture-device', 'test-mode', 'preset', 'crf', 'segment-duration', 'max-age']
    .forEach(id => $(id).addEventListener('change', () => { STATE.dirty = true; }));

  $('btn-save').addEventListener('click', save);
  $('btn-revert').addEventListener('click', () => fillForm(STATE.config));

  $('btn-shutdown').addEventListener('click', async () => {
    if (!confirm('Encerrar o sistema? Captura, player e cleaner vão parar.')) return;
    try {
      await api('/api/shutdown', { method: 'POST' });
      toast('Sistema encerrado');
    } catch {
      toast('Falha ao encerrar', 'err');
    }
  });

  // Atalhos: Cmd/Ctrl+S salva
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault();
      save();
    }
  });

  // Decide entre wizard e dashboard com base no setup-status
  try {
    const setup = await api('/api/setup-status');
    if (!setup.complete) {
      wireWizard();
      await loadWizardData();
      showWizard();
      renderWizardStep();
      return;  // não polla status até o wizard terminar
    }
    showDashboard();
    await loadAll();
  } catch (e) {
    toast('Falha ao carregar config', 'err');
    showDashboard();
  }
  pollStatus();
});
