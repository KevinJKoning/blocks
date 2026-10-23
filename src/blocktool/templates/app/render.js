// render.js: Markdown, downloads and CSV, shared by the report and the modals. (Charts and
// every other block are drawn in blocks.js.)

// ------------------------------------------------------------------ markdown (subset; links shown as text)
function inline(text, images) {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\))/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    out.push(text.slice(last, m.index));
    const t = m[0];
    if (t[0] === "`") out.push(h("code", {}, t.slice(1, -1)));
    else if (t.startsWith("**")) out.push(h("strong", {}, t.slice(2, -2)));
    else if (t[0] === "*") out.push(h("em", {}, t.slice(1, -1)));
    else if (t[0] === "!") {
      const [, alt, url] = t.match(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/);
      out.push(images && images[url] ? figure(images[url], url, alt) : h("span", { class: "muted" }, `[image: ${alt || url}]`));
    } else {
      const [, label, url] = t.match(/\[([^\]]+)\]\(([^)]+)\)/);
      out.push(label, h("span", { class: "muted" }, ` (${url})`));
    }
    last = re.lastIndex;
  }
  out.push(text.slice(last));
  return out;
}
function markdown(src, images) {
  const frag = h("div", {});
  const lines = src.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {
      const body = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++; frag.append(h("pre", { class: "src" }, body.join("\n"))); continue;
    }
    const hd = ln.match(/^(#{1,4})\s+(.*)/);
    if (hd) { frag.append(h(`h${Math.min(hd[1].length, 4)}`, {}, inline(hd[2], images))); i++; continue; }
    if (/^\|.*\|\s*$/.test(ln)) {
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().slice(1, -1).split("|").map((x) => x.trim());
      const body = rows.filter((r, j) => !(j === 1 && /^[\s|:-]+$/.test(r)));
      frag.append(h("table", { class: "kv md" }, h("thead", {}, h("tr", {}, cells(body[0]).map((x) => h("th", {}, inline(x, images))))),
        h("tbody", {}, body.slice(1).map((r) => h("tr", {}, cells(r).map((x) => h("td", {}, inline(x, images))))))));
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(ln)) {
      const ol = /^\s*\d+\./.test(ln);
      const list = h(ol ? "ol" : "ul", {});
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, "");
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) item += " " + lines[i++].trim();
        list.append(h("li", {}, inline(item, images)));
      }
      frag.append(list); continue;
    }
    if (!ln.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#|```|\||\s*([-*]|\d+\.)\s)/.test(lines[i])) para.push(lines[i++]);
    frag.append(h("p", {}, inline(para.join(" "), images)));
  }
  return frag;
}
function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type: type || "application/octet-stream" }));
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ------------------------------------------------------------------ CSV (quoted fields; numbers parsed)
function csvRows(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') quoted = false; else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  const header = rows.shift() || [];
  const num = (s) => (s.trim() !== "" && Number.isFinite(Number(s)) ? Number(s) : s);
  return { header, rows: rows.filter((r) => r.length > 1 || r[0] !== "").map((r) => r.map(num)) };
}
