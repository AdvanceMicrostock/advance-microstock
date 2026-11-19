// Prompt file import helpers (TXT / CSV). Pure functions, no DOM.

function cleanPrompt(s) {
  return String(s).replace(/\s*[\r\n]+\s*/g, ' ').trim();
}

// Quote-aware CSV parser (handles "a,b", "" escapes and multi-line cells)
function parseCsv(text) {
  const rows = [];
  let row = [], field = '', inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false;
      } else field += ch;
    } else if (ch === '"' && field === '') {
      inQ = true;
    } else if (ch === ',') {
      row.push(field); field = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = ''; rows.push(row); row = [];
    } else field += ch;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

const HEADER_RE = /^(prompts?|text|description|caption|idea|title|query)$/i;

function promptsFromTxt(text) {
  return text.replace(/^\uFEFF/, '').split(/\r?\n/).map(cleanPrompt).filter(Boolean);
}

function promptsFromCsv(text) {
  text = text.replace(/^\uFEFF/, '');
  const rows = parseCsv(text);
  if (!rows.length) return [];

  const widths = new Set(rows.map((r) => r.length));

  // Single column file
  if (widths.size === 1 && rows[0].length === 1) {
    let list = rows.map((r) => cleanPrompt(r[0]));
    if (HEADER_RE.test(list[0])) list.shift();
    return list.filter(Boolean);
  }

  // Rows have different column counts: prompts contain unquoted commas.
  // Treat every line as one whole prompt so nothing gets cut.
  if (widths.size > 1) {
    let list = promptsFromTxt(text);
    if (HEADER_RE.test(list[0])) list.shift();
    return list;
  }

  // Proper multi-column CSV
  const header = rows[0].map((c) => c.trim());
  let col = header.findIndex((c) => HEADER_RE.test(c));
  let body = rows;
  if (col >= 0) {
    body = rows.slice(1);
  } else {
    // No header name: use the column with the longest text on average
    let best = 0, bestLen = -1;
    for (let c = 0; c < rows[0].length; c++) {
      const avg = rows.reduce((s, r) => s + (r[c] || '').length, 0) / rows.length;
      if (avg > bestLen) { bestLen = avg; best = c; }
    }
    col = best;
  }
  return body.map((r) => cleanPrompt(r[col] || '')).filter(Boolean);
}

function promptsFromFile(name, text) {
  return /\.csv$/i.test(name) ? promptsFromCsv(text) : promptsFromTxt(text);
}

if (typeof module !== 'undefined') module.exports = { parseCsv, promptsFromTxt, promptsFromCsv, promptsFromFile };
