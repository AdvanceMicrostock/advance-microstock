// Whisk Prompt Automator – Popup Logic

const promptsTextarea = document.getElementById('prompts');
const promptCountBadge = document.getElementById('prompt-count');
const paceSlider = document.getElementById('pace-slider');
const paceValueLabel = document.getElementById('pace-value');
const btnStart = document.getElementById('btn-start');
const btnPause = document.getElementById('btn-pause');
const btnStop = document.getElementById('btn-stop');
const pauseText = document.getElementById('pause-text');
const tabStatusBadge = document.getElementById('tab-status');
const statusNotice = document.getElementById('status-notice');
const noticeText = document.getElementById('notice-text');
const progressBox = document.getElementById('progress-box');
const progressStatus = document.getElementById('progress-status');
const progressPercent = document.getElementById('progress-percent');
const progressBar = document.getElementById('progress-bar');
const progressCurrent = document.getElementById('progress-current');
const queueBox = document.getElementById('queue-box');
const queueList = document.getElementById('queue-list');
const queueSummary = document.getElementById('queue-summary');
const btnRemoveDone = document.getElementById('btn-remove-done');
const btnClear = document.getElementById('btn-clear');
const btnSidebar = document.getElementById('btn-sidebar');

const ICONS = { done: '✓', pending: '⏳', running: '▶', error: '✕' };
const btnImport = document.getElementById('btn-import');
const fileInput = document.getElementById('file-input');
let lastState = null;

let activeTabId = null;

function showNotice(text, type) {
  noticeText.textContent = text;
  statusNotice.classList.toggle('info', type === 'info');
  statusNotice.classList.remove('hidden');
}

function hideNotice() {
  statusNotice.classList.add('hidden');
}

function getPromptsList() {
  return promptsTextarea.value
    .split('\n')
    .map(p => p.trim())
    .filter(p => p.length > 0);
}

function updatePromptCount() {
  const count = getPromptsList().length;
  promptCountBadge.textContent = `${count} prompt${count === 1 ? '' : 's'}`;
  btnStart.disabled = count === 0;
}

promptsTextarea.addEventListener('input', () => {
  hideNotice();
  updatePromptCount();
  saveState();
});

paceSlider.addEventListener('input', () => {
  paceValueLabel.textContent = `${parseFloat(paceSlider.value).toFixed(1)}s`;
  saveState();
});

function saveState() {
  const data = { prompts: promptsTextarea.value, pace: paceSlider.value };
  // 1) synchronous copy: survives the popup closing instantly
  try {
    localStorage.setItem('wfa_prompts', data.prompts);
    localStorage.setItem('wfa_pace', data.pace);
  } catch (e) {}
  // 2) extension storage
  try {
    chrome.storage.local.set(data, () => {
      if (chrome.runtime.lastError) showNotice('Could not save prompts: ' + chrome.runtime.lastError.message);
    });
  } catch (e) {}
}

// Save at every moment the popup/sidebar might disappear
['paste', 'cut', 'change', 'blur'].forEach((ev) =>
  promptsTextarea.addEventListener(ev, () => setTimeout(saveState, 0))
);
window.addEventListener('pagehide', saveState);
window.addEventListener('beforeunload', saveState);
document.addEventListener('visibilitychange', () => { if (document.hidden) saveState(); });

function loadState() {
  chrome.storage.local.get(['prompts', 'pace', 'automatorState'], (data) => {
    data = data || {};
    let ls = null, lsPace = null;
    try {
      ls = localStorage.getItem('wfa_prompts');
      lsPace = localStorage.getItem('wfa_pace');
    } catch (e) {}

    // The synchronous copy is the newest; fall back to extension storage
    let prompts = ls !== null ? ls : data.prompts;
    const pace = lsPace !== null ? lsPace : data.pace;

    // Last resort: rebuild the box from a saved queue that still has pending prompts
    const q = data.automatorState;
    if ((prompts === undefined || prompts === null) && q && q.prompts && q.prompts.length) {
      prompts = q.prompts.filter((p, i) => (q.statuses || [])[i] !== 'done').join('\n');
    }

    if (prompts !== undefined && prompts !== null) promptsTextarea.value = prompts;
    if (pace !== undefined && pace !== null) {
      paceSlider.value = pace;
      paceValueLabel.textContent = `${parseFloat(pace).toFixed(1)}s`;
    }

    updatePromptCount();
    if (promptsTextarea.value) saveState(); // make sure both copies agree

    if (q && q.prompts && q.prompts.length) syncUI(q);
  });
}

function isWhiskOrFlow(url) {
  return url.includes('flow.google.com') || url.includes('scf.usercontent.goog') || url.includes('labs.google');
}

function checkTab(cb) {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || tabs.length === 0) return;
    const tab = tabs[0];
    activeTabId = tab.id;
    if (isWhiskOrFlow(tab.url || '')) {
      tabStatusBadge.className = 'badge connected';
      tabStatusBadge.textContent = '● Connected';
      tabStatusBadge.title = 'Whisk / Flow tab found';
    } else {
      tabStatusBadge.className = 'badge disconnected';
      tabStatusBadge.textContent = '○ No tab';
      tabStatusBadge.title = 'Open a Whisk or Flow tab first';
    }
    if (cb) cb();
  });
}

// Sidebar mode: follow the active tab
chrome.tabs.onActivated.addListener(() => checkTab());
chrome.tabs.onUpdated.addListener((id, info) => { if (info.url || info.status === 'complete') checkTab(); });

// Switch between popup mode and sidebar mode (remembered for the next icon click)
const isSide = document.body.classList.contains('side');

async function currentWindowId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs && tabs[0] ? tabs[0].windowId : undefined;
}

btnSidebar.addEventListener('click', async () => {
  try {
    const windowId = await currentWindowId();
    if (!isSide) {
      // popup -> sidebar
      const opened = chrome.sidePanel.open({ windowId });
      await chrome.action.setPopup({ popup: '' });
      await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
      await chrome.storage.local.set({ uiMode: 'side' });
      await opened;
      window.close();
    } else {
      // sidebar -> popup (background closes the panel and opens the popup)
      showNotice('Switching to popup… (if nothing opens, click the extension icon)');
      noticeText.parentElement.style.borderColor = '';
      chrome.runtime.sendMessage({ action: 'SWITCH_TO_POPUP', tabId: activeTabId });
    }
  } catch (e) {
    showNotice('Could not switch mode: ' + e.message);
  }
});

btnStart.addEventListener('click', () => checkTab(startAutomation));

function startAutomation() {
  hideNotice();
  const prompts = getPromptsList();
  if (prompts.length === 0) return;

  const delayMs = Math.round(parseFloat(paceSlider.value) * 1000);

  chrome.runtime.sendMessage({
    action: 'START_AUTOMATION',
    tabId: activeTabId,
    config: {
      prompts,
      delay: delayMs
    }
  }, (res) => {
    if (res && res.error) {
      showNotice(res.error);
    } else if (res && res.success) {
      btnStart.classList.add('hidden');
      btnPause.classList.remove('hidden');
      btnStop.classList.remove('hidden');
      progressBox.classList.remove('hidden');
      pauseText.textContent = '⏸ Pause';
    }
  });
}

btnPause.addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'TOGGLE_PAUSE', tabId: activeTabId }, (res) => {
    if (res && res.isPaused !== undefined) {
      pauseText.textContent = res.isPaused ? '▶ Resume' : '⏸ Pause';
    }
  });
});

btnStop.addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'STOP_AUTOMATION' }, () => {
    btnStart.classList.remove('hidden');
    btnPause.classList.add('hidden');
    btnStop.classList.add('hidden');
  });
});

const QUEUE_WINDOW = 40;

function makeRow(i, p, st) {
  const row = document.createElement('div');
  row.className = `q-item ${st}`;
  row.title = p;
  const icon = document.createElement('span');
  icon.className = 'q-icon';
  icon.textContent = ICONS[st] || '⏳';
  const text = document.createElement('span');
  text.className = 'q-text';
  text.textContent = `${i + 1}. ${p}`;
  row.append(icon, text);
  return row;
}

function makeNote(text) {
  const n = document.createElement('div');
  n.className = 'q-note';
  n.textContent = text;
  return n;
}

function renderQueue(state) {
  const prompts = state.prompts || [];
  const statuses = state.statuses || [];
  if (!prompts.length) {
    queueBox.classList.add('hidden');
    return;
  }
  queueBox.classList.remove('hidden');

  let done = 0, pending = 0, errors = 0;
  for (let i = 0; i < prompts.length; i++) {
    const st = statuses[i] || 'pending';
    if (st === 'done') done++; else if (st === 'error') errors++; else pending++;
  }
  queueSummary.textContent = `${done} done · ${pending} pending` + (errors ? ` · ${errors} failed` : '');

  // Only draw a window around the current prompt
  const cur = Math.min(state.currentIndex || 0, prompts.length - 1);
  const start = Math.max(0, cur - 3);
  const end = Math.min(prompts.length, start + QUEUE_WINDOW);

  queueList.innerHTML = '';
  if (start > 0) queueList.appendChild(makeNote(`↑ ${start} earlier`));
  for (let i = start; i < end; i++) queueList.appendChild(makeRow(i, prompts[i], statuses[i] || 'pending'));
  if (end < prompts.length) queueList.appendChild(makeNote(`↓ ${prompts.length - end} more`));

  const active = queueList.querySelector('.running, .error');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

btnRemoveDone.addEventListener('click', () => {
  if (!lastState) return;
  const keep = (lastState.prompts || []).filter((p, i) => (lastState.statuses || [])[i] !== 'done');
  promptsTextarea.value = keep.join('\n');
  saveState();
  updatePromptCount();
  chrome.runtime.sendMessage({ action: 'CLEAR_QUEUE' }, () => {
    lastState = null;
    renderQueue({});
    progressBox.classList.add('hidden');
    btnStart.classList.remove('hidden');
    btnPause.classList.add('hidden');
    btnStop.classList.add('hidden');
  });
});

btnClear.addEventListener('click', () => {
  promptsTextarea.value = '';
  saveState();
  updatePromptCount();
  chrome.runtime.sendMessage({ action: 'CLEAR_QUEUE' }, () => {
    lastState = null;
    renderQueue({});
    progressBox.classList.add('hidden');
    btnStart.classList.remove('hidden');
    btnPause.classList.add('hidden');
    btnStop.classList.add('hidden');
  });
});

function syncUI(state) {
  if (state.prompts) { lastState = state; renderQueue(state); }
  if (state.isRunning) {
    btnStart.classList.add('hidden');
    btnPause.classList.remove('hidden');
    btnStop.classList.remove('hidden');
    progressBox.classList.remove('hidden');
    pauseText.textContent = state.isPaused ? '▶ Resume' : '⏸ Pause';

    const pct = state.total > 0 ? Math.round((state.currentIndex / state.total) * 100) : 0;
    progressPercent.textContent = `${pct}%`;
    progressBar.style.width = `${pct}%`;
    progressStatus.textContent = state.interrupted
      ? `Interrupted at ${state.currentIndex + 1} of ${state.total} – press Resume`
      : state.isPaused
        ? `Paused at ${state.currentIndex + 1} of ${state.total}`
        : `Submitting ${state.currentIndex + 1} of ${state.total}...`;
    progressCurrent.textContent = state.currentPrompt || '-';
  } else {
    btnStart.classList.remove('hidden');
    btnPause.classList.add('hidden');
    btnStop.classList.add('hidden');
    if (state.completed) {
      progressBox.classList.remove('hidden');
      progressBar.style.width = '100%';
      progressPercent.textContent = '100%';
      progressStatus.textContent = `Done! Submitted all ${state.total} prompts.`;
      progressCurrent.textContent = 'Completed successfully.';
    }
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'AUTOMATION_PROGRESS') {
    syncUI(msg.state);
  } else if (msg.action === 'AUTOMATION_COMPLETE') {
    // final state arrives via AUTOMATION_PROGRESS
  } else if (msg.action === 'AUTOMATION_ERROR') {
    showNotice((msg.error || 'Failed to submit prompt.') + ' (press Resume to retry)');
  }
});

// ---------- Import prompts from .txt / .csv ----------
async function importFiles(fileList) {
  const files = Array.from(fileList || []).filter((f) => /\.(txt|csv)$/i.test(f.name) || /^text\//.test(f.type));
  if (!files.length) {
    showNotice('Please choose a .txt or .csv file.');
    return;
  }
  const all = [];
  for (const f of files) {
    try {
      all.push(...promptsFromFile(f.name, await f.text()));
    } catch (e) {
      showNotice(`Could not read ${f.name}: ${e.message}`);
      return;
    }
  }
  if (!all.length) {
    showNotice('No prompts found in the file.');
    return;
  }
  const existing = promptsTextarea.value.trim();
  promptsTextarea.value = existing ? existing + '\n' + all.join('\n') : all.join('\n');
  updatePromptCount();
  saveState();
  const names = files.length === 1 ? files[0].name : `${files.length} files`;
  showNotice(`Added ${all.length} prompt${all.length === 1 ? '' : 's'} from ${names}`, 'info');
}

btnImport.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', async () => {
  await importFiles(fileInput.files);
  fileInput.value = '';
});

['dragenter', 'dragover'].forEach((ev) =>
  promptsTextarea.addEventListener(ev, (e) => {
    if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
      e.preventDefault();
      promptsTextarea.classList.add('drag-over');
    }
  })
);
['dragleave', 'drop'].forEach((ev) =>
  promptsTextarea.addEventListener(ev, () => promptsTextarea.classList.remove('drag-over'))
);
promptsTextarea.addEventListener('drop', async (e) => {
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
    e.preventDefault();
    await importFiles(e.dataTransfer.files);
  }
});

// Init
checkTab();
loadState();
