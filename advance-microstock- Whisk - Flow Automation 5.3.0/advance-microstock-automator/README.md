# Advance Microstock – Whisk / Flow Automation

Batch prompt automator for Google Whisk and Flow (Chrome, Manifest V3).

- Works on flow.google.com and labs.google (Whisk + Flow)
- Per-prompt status: done / pending / failed
- Queue survives Chrome restart (resume where it stopped)
- "Remove done" keeps only the pending prompts
- Works as a popup AND as a sidebar. Use the ◧ Side / ▭ Popup button to switch; the extension icon then opens whichever mode you last chose.
- Import prompts from .txt or .csv (Import button or drag & drop onto the prompt box)
- Prompts are saved automatically (double backup) and come back every time the popup/sidebar opens

Install: chrome://extensions -> Developer mode -> Load unpacked -> select this folder.
After updating, reload the extension and press F5 on the Whisk/Flow tab.
