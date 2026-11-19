// Whisk / Flow Prompt Automator – Background Service Worker
// Per-prompt status + queue survives browser restarts (resumes as paused)

function defaultState() {
  return {
    isRunning: false,
    isPaused: false,
    completed: false,
    interrupted: false,
    prompts: [],
    statuses: [], // 'pending' | 'running' | 'done' | 'error'
    currentIndex: 0,
    total: 0,
    currentPrompt: '',
    delay: 1200,
    tabId: null
  };
}

let queueState = defaultState();
let timerId = null;
let busy = false;

// Restore saved queue after service worker restart / Chrome reopen
const ready = chrome.storage.local.get('automatorState').then((data) => {
  const saved = data.automatorState;
  if (saved && saved.prompts && saved.prompts.length) {
    queueState = Object.assign(defaultState(), saved);
    if (queueState.isRunning && !queueState.isPaused) {
      // Was interrupted (Chrome closed / worker killed): wait for the user to resume
      queueState.isPaused = true;
      queueState.interrupted = true;
      if (queueState.statuses[queueState.currentIndex] === 'running') {
        queueState.statuses[queueState.currentIndex] = 'pending';
      }
    }
    updateBadge();
    saveState();
  }
});

function saveState() {
  chrome.storage.local.set({ automatorState: queueState });
}

function updateBadge() {
  if (queueState.isRunning) {
    chrome.action.setBadgeText({ text: `${Math.min(queueState.currentIndex + 1, queueState.total)}/${queueState.total}` });
    chrome.action.setBadgeBackgroundColor({ color: queueState.isPaused ? '#f59e0b' : '#6366f1' });
  } else if (queueState.completed) {
    chrome.action.setBadgeText({ text: '✓' });
    chrome.action.setBadgeBackgroundColor({ color: '#10b981' });
  } else {
    chrome.action.setBadgeText({ text: '' });
  }
}

function broadcastProgress() {
  updateBadge();
  saveState();
  chrome.runtime.sendMessage({ action: 'AUTOMATION_PROGRESS', state: queueState }).catch(() => {});
}

async function ensureContentScriptInAllFrames(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content.js']
    });
    await new Promise((r) => setTimeout(r, 150));
  } catch (err) {
    // ignore: manifest content script may already be present
  }
}

function fail(errorMsg) {
  queueState.statuses[queueState.currentIndex] = 'error';
  queueState.isPaused = true; // Resume will retry this same prompt
  broadcastProgress();
  chrome.runtime.sendMessage({ action: 'AUTOMATION_ERROR', error: errorMsg }).catch(() => {});
}

async function runNextPrompt() {
  if (busy || !queueState.isRunning || queueState.isPaused) return;

  if (queueState.currentIndex >= queueState.total) {
    queueState.isRunning = false;
    queueState.completed = true;
    updateBadge();
    saveState();
    chrome.runtime.sendMessage({ action: 'AUTOMATION_COMPLETE', total: queueState.total }).catch(() => {});
    chrome.runtime.sendMessage({ action: 'AUTOMATION_PROGRESS', state: queueState }).catch(() => {});
    return;
  }

  busy = true;
  const index = queueState.currentIndex;
  const prompt = queueState.prompts[index];
  queueState.currentPrompt = prompt;
  queueState.statuses[index] = 'running';
  broadcastProgress();

  try {
    await ensureContentScriptInAllFrames(queueState.tabId);

    const res = await chrome.tabs.sendMessage(queueState.tabId, {
      action: 'SUBMIT_SINGLE_PROMPT',
      prompt,
      index,
      total: queueState.total
    });

    if (!res || !res.success) {
      busy = false;
      fail((res && res.error) || 'Input box not found. Is the Whisk/Flow page open?');
      return;
    }

    queueState.statuses[index] = 'done';
    queueState.currentIndex = index + 1;
    busy = false;
    broadcastProgress();

    if (queueState.isRunning && !queueState.isPaused) {
      timerId = setTimeout(runNextPrompt, queueState.delay || 1200);
    }
  } catch (err) {
    busy = false;
    fail(err.message || 'Could not reach the page.');
  }
}

async function handleMessage(request) {
  await ready;

  if (request.action === 'START_AUTOMATION') {
    const { config, tabId } = request;
    if (!tabId) return { error: 'Please open Whisk or Flow first.' };

    if (timerId) clearTimeout(timerId);
    busy = false;
    queueState = Object.assign(defaultState(), {
      isRunning: true,
      prompts: config.prompts,
      statuses: config.prompts.map(() => 'pending'),
      total: config.prompts.length,
      currentPrompt: config.prompts[0],
      delay: config.delay,
      tabId
    });
    broadcastProgress();
    runNextPrompt();
    return { success: true };
  }

  if (request.action === 'TOGGLE_PAUSE') {
    queueState.isPaused = !queueState.isPaused;
    if (!queueState.isPaused) {
      queueState.interrupted = false;
      if (request.tabId) queueState.tabId = request.tabId;
    }
    broadcastProgress();
    if (!queueState.isPaused && queueState.isRunning) runNextPrompt();
    return { isPaused: queueState.isPaused };
  }

  if (request.action === 'STOP_AUTOMATION') {
    if (timerId) clearTimeout(timerId);
    busy = false;
    queueState.isRunning = false;
    queueState.isPaused = false;
    queueState.interrupted = false;
    // statuses are kept so you can still see what was done / pending
    broadcastProgress();
    return { success: true };
  }

  if (request.action === 'CLEAR_QUEUE') {
    if (timerId) clearTimeout(timerId);
    busy = false;
    queueState = defaultState();
    broadcastProgress();
    return { success: true };
  }

  if (request.action === 'GET_STATE') {
    return { state: queueState };
  }

  if (request.action === 'SWITCH_TO_POPUP') {
    // Runs here (not in the side panel page) because the panel page dies when the panel closes
    const tabId = request.tabId;
    try {
      await chrome.action.setPopup({ popup: 'popup.html' });
      await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
      await chrome.storage.local.set({ uiMode: 'popup' });
    } catch (e) {}
    // Disabling the side panel for this tab is what actually closes it
    try { await chrome.sidePanel.setOptions({ tabId, enabled: false }); } catch (e) {}
    await new Promise((r) => setTimeout(r, 350));
    // Re-enable so the "Side" button can open it again later
    try { await chrome.sidePanel.setOptions({ tabId, path: 'sidepanel.html', enabled: true }); } catch (e) {}
    try { await chrome.action.openPopup(); } catch (e) { /* user can just click the icon */ }
    return { success: true };
  }

  return undefined;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  // Only handle messages meant for the background worker
  const mine = ['START_AUTOMATION', 'TOGGLE_PAUSE', 'STOP_AUTOMATION', 'CLEAR_QUEUE', 'GET_STATE', 'SWITCH_TO_POPUP'];
  if (!mine.includes(request.action)) return false;
  handleMessage(request).then(sendResponse);
  return true;
});


// ---------- Popup / sidebar mode ----------
// uiMode = 'popup' (icon opens popup) or 'side' (icon opens sidebar)
async function applyUiMode() {
  try {
    const { uiMode } = await chrome.storage.local.get('uiMode');
    const side = uiMode === 'side';
    await chrome.action.setPopup({ popup: side ? '' : 'popup.html' });
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: side });
  } catch (e) {}
}

applyUiMode();
chrome.runtime.onInstalled.addListener(applyUiMode);
chrome.runtime.onStartup.addListener(applyUiMode);
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.uiMode) applyUiMode();
});
