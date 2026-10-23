// Tiny SVG scatter/line helper shared by this app's views.
window.plot = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, ...kids) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    e.append(...kids);
    return e;
  };
  const extent = (xs) => { const lo = Math.min(...xs), hi = Math.max(...xs); return lo === hi ? [lo - 1, hi + 1] : [lo, hi]; };
  const fmt = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : Number(v.toPrecision(3)).toString()) : String(v ?? "–"));

  // series: [{points: [[x, y], ...], kind: "dot" | "line", cls, title?: (p) => string}]
  function chart({ series, width = 440, height = 230, xLabel = "", yLabel = "", hlines = [] }) {
    const P = { l: 44, r: 10, t: 10, b: 30 };
    const all = series.flatMap((s) => s.points);
    const [x0, x1] = extent(all.map((p) => p[0])), [y0, y1] = extent([...all.map((p) => p[1]), ...hlines]);
    const sx = (x) => P.l + ((x - x0) / (x1 - x0)) * (width - P.l - P.r);
    const sy = (y) => height - P.b - ((y - y0) / (y1 - y0)) * (height - P.t - P.b);
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", class: "chart", role: "img" });
    svg.append(el("line", { x1: P.l, y1: height - P.b, x2: width - P.r, y2: height - P.b, class: "axis" }),
      el("line", { x1: P.l, y1: P.t, x2: P.l, y2: height - P.b, class: "axis" }));
    for (const [v, y] of [[y0, sy(y0)], [y1, sy(y1)]]) svg.append(el("text", { x: P.l - 4, y: y + 4, "text-anchor": "end" }, fmt(v)));
    for (const [v, x] of [[x0, sx(x0)], [x1, sx(x1)]]) svg.append(el("text", { x, y: height - P.b + 14, "text-anchor": "middle" }, fmt(v)));
    svg.append(el("text", { x: (P.l + width - P.r) / 2, y: height - 4, "text-anchor": "middle" }, xLabel),
      el("text", { x: 10, y: (P.t + height - P.b) / 2, transform: `rotate(-90 10 ${(P.t + height - P.b) / 2})`, "text-anchor": "middle" }, yLabel));
    for (const v of hlines) svg.append(el("line", { x1: P.l, x2: width - P.r, y1: sy(v), y2: sy(v), class: "ref" }));
    for (const s of series) {
      if (s.kind === "line") {
        svg.append(el("polyline", { points: s.points.map((p) => `${sx(p[0])},${sy(p[1])}`).join(" "), class: `line ${s.cls || ""}` }));
      } else {
        for (const p of s.points) {
          const c = el("circle", { cx: sx(p[0]), cy: sy(p[1]), r: 2.6, class: `dot ${typeof s.cls === "function" ? s.cls(p) : s.cls || ""}` });
          if (s.title) c.append(el("title", {}, s.title(p)));
          svg.append(c);
        }
      }
    }
    return svg;
  }
  return { chart, fmt };
})();
