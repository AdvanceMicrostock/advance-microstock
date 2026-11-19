// Whisk / Flow Prompt Automator – Content Script
// Works in all frames. Supports:
//  - Whisk: input .whisk-prompt-input + button with <span>arrow_forward</span>
//  - Flow : rich-text (contenteditable) prompt box + round arrow submit button

(function () {
  if (window.__WHISK_IFRAME_CONTENT_SCRIPT__) return;
  window.__WHISK_IFRAME_CONTENT_SCRIPT__ = true;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function querySelectorDeepAll(selector, root = document) {
    const results = [];
    try {
      results.push(...Array.from(root.querySelectorAll(selector)));
    } catch (e) {}
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
    let node = walker.nextNode();
    while (node) {
      if (node.shadowRoot) results.push(...querySelectorDeepAll(selector, node.shadowRoot));
      node = walker.nextNode();
    }
    return results;
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return (rect.width > 0 || rect.height > 0) && window.getComputedStyle(el).visibility !== 'hidden';
  }

  function isEditable(el) {
    return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
  }

  // ---------- Find the prompt input ----------
  function findPromptInput() {
    // 1. Whisk
    for (const el of querySelectorDeepAll('.whisk-prompt-input, [class*="whisk-prompt-input"]')) {
      if (!isVisible(el)) continue;
      if (isEditable(el)) return el;
      const inner = el.querySelector('input, textarea, [contenteditable="true"], [contenteditable="plaintext-only"]');
      if (inner && isVisible(inner)) return inner;
      return el;
    }

    // 2a. Flow: prompt box container
    for (const box of querySelectorDeepAll('.prompt-box-container')) {
      const inner = Array.from(box.querySelectorAll(
        'textarea, [role="textbox"], [contenteditable="true"], [contenteditable="plaintext-only"]'
      )).find((el) => isVisible(el) && isEditable(el));
      if (inner) return inner;
    }

    // 2b. Generic: textarea, textbox, contenteditable
    const cands = querySelectorDeepAll(
      'textarea, [role="textbox"], [contenteditable="true"], [contenteditable="plaintext-only"], input[type="text"]'
    ).filter((el) => isVisible(el) && isEditable(el));

    if (cands.length === 0) return null;

    // Prefer the one that has a submit button nearby, then the biggest one
    const withButton = cands.filter((el) => findSubmitButton(el));
    const pool = withButton.length ? withButton : cands;
    pool.sort((a, b) => {
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      return rb.width * rb.height - ra.width * ra.height;
    });
    return pool[0];
  }

  // ---------- Find the submit button ----------
  function hasArrowForward(btn) {
    if (btn.textContent && btn.textContent.includes('arrow_forward')) return true;
    return !!btn.querySelector('.arrow_forward, [class*="arrow_forward"]');
  }

  function findSubmitButton(inputEl) {
    const allButtons = querySelectorDeepAll('button, [role="button"]').filter(isVisible);

    // 0. Flow: the round generate button
    const flowBtn = allButtons.find((b) => b.matches('button.generate-icon-button, .generate-icon-button'));
    if (flowBtn) return flowBtn;

    // 1. Button with arrow_forward icon (Whisk, and Flow if it uses material icons)
    const arrow = allButtons.filter(hasArrowForward);
    if (arrow.length) {
      if (inputEl && arrow.length > 1) {
        const ir = inputEl.getBoundingClientRect();
        arrow.sort((a, b) => dist(a, ir) - dist(b, ir));
      }
      return arrow[0];
    }

    // 2. Look near the input: climb ancestors until a container has 2+ buttons,
    //    then pick the right-most / bottom-most one (the round arrow button)
    if (inputEl) {
      let container = inputEl.parentElement;
      for (let i = 0; i < 10 && container; i++) {
        const btns = Array.from(container.querySelectorAll('button, [role="button"]')).filter(isVisible);
        if (btns.length >= 2) {
          // prefer explicit labels
          const labelled = btns.find((b) => /create|generate|send|submit|run/i.test((b.getAttribute('aria-label') || '') + ' ' + (b.title || '')));
          if (labelled) return labelled;
          btns.sort((a, b) => {
            const ra = a.getBoundingClientRect();
            const rb = b.getBoundingClientRect();
            return rb.right - ra.right || rb.bottom - ra.bottom;
          });
          return btns[0];
        }
        container = container.parentElement;
      }
    }
    return null;
  }

  function dist(btn, rect) {
    const b = btn.getBoundingClientRect();
    return Math.abs(b.left - rect.right) + Math.abs(b.top - rect.bottom);
  }

  function isEnabled(btn) {
    return btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true' && !btn.hasAttribute('disabled') && !btn.classList.contains('mat-mdc-button-disabled');
  }

  // ---------- Put text into the input ----------
  function currentText(el) {
    return (el.value !== undefined ? el.value : el.innerText || el.textContent || '').trim();
  }

  function injectPrompt(el, text) {
    el.focus();

    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      const proto = el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(el, text);
      else el.value = text;
      el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      el.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
      return;
    }

    // Rich-text editor (contenteditable, e.g. Flow): select all, then real "typing"
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);

    let ok = false;
    try {
      ok = document.execCommand('insertText', false, text);
    } catch (e) {}

    // Fallback: simulate paste
    if (!ok || currentText(el) === '') {
      try {
        const dt = new DataTransfer();
        dt.setData('text/plain', text);
        el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true, composed: true }));
      } catch (e) {}
    }

    // Last resort
    if (currentText(el) === '') {
      el.textContent = text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, composed: true, inputType: 'insertText', data: text }));
    }
  }

  // ---------- Click like a real user ----------
  function realClick(btn) {
    const opts = { bubbles: true, cancelable: true, composed: true, view: window };
    btn.dispatchEvent(new PointerEvent('pointerdown', opts));
    btn.dispatchEvent(new MouseEvent('mousedown', opts));
    btn.dispatchEvent(new PointerEvent('pointerup', opts));
    btn.dispatchEvent(new MouseEvent('mouseup', opts));
    btn.click();
  }

  async function waitForButton(inputEl, timeout = 4000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const btn = findSubmitButton(inputEl);
      if (btn && isEnabled(btn)) return btn;
      await sleep(120);
    }
    return null;
  }

  async function submitPrompt(inputEl, prompt) {
    injectPrompt(inputEl, prompt);
    await sleep(250);

    let btn = await waitForButton(inputEl);

    // If button never enabled, try typing again once
    if (!btn) {
      injectPrompt(inputEl, prompt);
      await sleep(400);
      btn = await waitForButton(inputEl, 3000);
    }

    if (!btn) {
      return { success: false, error: 'Submit button is not enabled. The page did not accept the text.' };
    }

    realClick(btn);
    return { success: true, prompt, frameUrl: window.location.href };
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'PING') {
      const inputEl = findPromptInput();
      sendResponse({ status: 'PONG', hasInput: !!inputEl, hasButton: !!findSubmitButton(inputEl), frameUrl: window.location.href });
      return true;
    }

    if (request.action === 'SUBMIT_SINGLE_PROMPT') {
      const inputEl = findPromptInput();
      if (!inputEl) return false; // not the right frame

      submitPrompt(inputEl, request.prompt)
        .then(sendResponse)
        .catch((err) => sendResponse({ success: false, error: err.message }));
      return true;
    }
  });
})();
