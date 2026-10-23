// In the prepare node's Documentation: what the measurements look like before anything
// runs: how many paired readings, how many have a missing value, and reading against
// reference. It reads only the dataset (DuckDB confines its SQL to it), so it also previews
// a file the viewer has just swapped in.
(() => {
  const root = document.getElementById("view");
  const note = Object.assign(document.createElement("p"), { className: "muted" });
  const box = document.createElement("div");
  root.append(note, box);
  const PATH = "data/measurements.parquet";
  const MISSING = "coalesce(isnan(reading), true) OR coalesce(isnan(reference), true)";

  // Same data, same drawing: a repeated state returns the drawing already under way.
  let shownFor = null, drawing = Promise.resolve();
  function show(state) {
    const d = state.data.measurements || {};
    const key = JSON.stringify([state.ready, d.status, d.file, d.original]);
    if (key === shownFor) return drawing;
    shownFor = key;
    drawing = (async () => {
      if (!state.ready || d.status !== "mounted") {
        box.replaceChildren();
        note.textContent = !state.ready ? "Starting the Python runtime…" : "Provide the measurements to see a preview.";
        bridge.describe({ rows: null });
        return;
      }
      const s = await bridge.query(`SELECT count(*), count(*) FILTER (WHERE ${MISSING}), min(reading), max(reading) FROM '${PATH}'`);
      const [n, missing, lo, hi] = s.rows[0];
      const pts = await bridge.query(`SELECT reading, reference FROM '${PATH}' WHERE NOT (${MISSING})`, 5000);
      note.textContent = `${n} paired readings${d.file ? ` from ${d.file}` : ""}, ${missing} with a missing value; ` +
        `readings from ${plot.fmt(lo)} to ${plot.fmt(hi)}. Spikes and dropouts are screened by the prepare stage.`;
      box.replaceChildren(plot.chart({ xLabel: "reading", yLabel: "reference", height: 210, series: [{ points: pts.rows }] }));
      bridge.describe({ rows: n, missing, plotted: pts.rows.length });
    })();
    return drawing;
  }
  bridge.on("update", show);
  bridge.init.then(async (s) => { await show(s); bridge.ready(); });
})();
