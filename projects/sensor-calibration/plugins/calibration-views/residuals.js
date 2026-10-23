// Residual explorer (in the evaluate node's results): held-out residuals against the reading,
// with a threshold the reader can move to see where the curve misses most.
(() => {
  const root = document.getElementById("view");
  const input = Object.assign(document.createElement("input"), { type: "range", min: "0.05", max: "1.5", step: "0.05", value: "0.5" });
  input.setAttribute("aria-label", "Residual threshold");
  const label = document.createElement("label");
  const value = document.createElement("span");
  label.append("Flag |residual| above ", value, " ", input);
  const box = document.createElement("div");
  const note = Object.assign(document.createElement("p"), { className: "muted" });
  root.append(label, box, note);

  // Same outputs, same drawing: a repeated state returns the drawing already under way.
  let points = null, loadedFor = null, loading = Promise.resolve();
  function load(state) {
    const ev = state.nodes.evaluate;
    const key = JSON.stringify([ev.status, ev.metrics]);
    if (key === loadedFor) return loading;
    loadedFor = key;
    loading = (async () => {
      const out = await bridge.read("evaluate");   // the node's output, as JSON
      points = out.reading.map((x, i) => [x, out.residual[i]]);
      draw();
    })();
    return loading;
  }
  function draw() {
    if (!points) return;   // the slider moved before the first read finished
    const t = Number(input.value);
    value.textContent = t.toFixed(2);
    const over = points.filter((p) => Math.abs(p[1]) > t).length;
    box.replaceChildren(plot.chart({
      xLabel: "reading", yLabel: "residual", hlines: [0, t, -t],
      series: [{ points, cls: (p) => (Math.abs(p[1]) > t ? "over" : ""), title: (p) => `reading ${plot.fmt(p[0])}, residual ${plot.fmt(p[1])}` }],
    }));
    note.textContent = `${over} of ${points.length} held-out points miss by more than ${t.toFixed(2)}.`;
    bridge.describe({ points: points.length, threshold: t, over });
  }
  input.addEventListener("input", draw);
  bridge.on("update", load);   // returns its promise: the bridge reports when drawing is done
  bridge.init.then(async (s) => { await load(s); bridge.ready({ points: points.length }); });
})();
