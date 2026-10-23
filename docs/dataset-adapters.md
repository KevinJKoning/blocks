# Dataset adapters

Status: implemented, with one adapter (`gdb-zip`, a built-in plugin). Builds on `ARCHITECTURE.md` and `docs/plugins.md`.

## Problem

Datasets are read in place: a file is mounted with WORKERFS and the nodes read it with
DuckDB or pyarrow. That works when the file already is what the nodes read (Parquet,
CSV). Some data does not arrive that way. GIS teams share an Esri file geodatabase as a
zipped folder (Windows: "Send to > Compressed (zipped) folder"), often several GB, of which
an app needs one feature class. Converting it outside the app would be a native data
step, which the repo does not allow, and asking every viewer to do it is not an option.

Goal: a dataset can declare a `format`, and the app turns the viewer's file into the
dataset the nodes read, in the browser, before any run. It must be modular (a new
format is one Python module, not changes across the template), show progress with an
estimate of the time left, and keep the repo's properties: everything runs in Pyodide,
every script is pinned by hash, the final app makes no network requests, and runs are
verified against the baseline.

## Declaration (`app.yaml`)

```yaml
data:
  parcels:
    path: data/parcels.gdb.zip   # the project's copy (what baselines are recorded with)
    at: data/parcels.parquet     # where nodes read the converted dataset
    format: gdb-zip
    layer: Parcels               # the adapter's options
    inline: false                # the viewer picks the file (see Builds)
```

A node that takes `parcels` as an input gets the converted file's path (`at`), never the
source:

```python
def areas(parcels, *, min_area_m2=1000):
    table = pq.read_table(parcels, columns=["LANDUSE", "ASSESSED", "geometry"])
```

`spec.py` rejects an unknown format, unknown options, a directory, and options without a
`format` (`layer:` on a plain dataset is a mistake, not ignored). A wrong layer fails in
the CLI with the layers that exist.

## The adapter contract (a plugin's `formats`)

An adapter is one Python module of a plugin (`formats: {gdb-zip: gdb_zip.py}` in its
`plugin.yaml`; the app lists the plugin). The same source runs natively (`spec.py`, when an app
is loaded) and in the browser (packed into the page as a hashed component, run in the
ingest worker), so its module level uses the standard library only.

| attribute | meaning |
|---|---|
| `NAME`, `VERSION` | the `format:` value; bump `VERSION` when the output changes |
| `PACKAGES` | Pyodide packages that `convert` loads (gdb-zip: `fiona`, `pyarrow`) |
| `OUTPUT`, `UNIT` | output file name inside the dataset mount; what progress counts (`features`) |
| `OPTIONS` | the dataset keys it accepts in `app.yaml` |
| `check_options(opts)` | validated options, or `ValueError` |
| `describe(opts)` | what the viewer is asked for, shown in the data row |
| `inspect(path, opts)` | stdlib only and cheap: `fingerprint`, `total`, `bytes`, and anything else useful |
| `convert(path, opts, out, progress)` | write `OUTPUT` to the binary file `out`, calling `progress(done, total, phase)` |

Adding a format: write the module, list it under `formats:` in a plugin's `plugin.yaml`
(built-in: `src/blocktool/plugins/<name>/`), test `inspect` natively.
Nothing in the app script, `worker.js` or `build.py` names a format.

### gdb-zip

- **`inspect`** reads the zip index and two small entries (the catalog,
  `a00000001.gdbtable/.gdbtablx`, parsed by about 80 lines of stdlib code) to map the layer name to
  its table `aXXXXXXXX`, and the table header for the feature count. It finds the `.gdb`
  folder at any depth (`gdb:` chooses when there are several). Its **fingerprint** hashes the
  layer, the adapter's name and version, and the name, size and CRC-32 (from the zip index)
  of every entry `convert` reads: the catalog, the `GDB_*` system tables and the layer's own
  files. The same geodatabase zipped again, by another tool, with another compression or
  under another folder, has the same fingerprint; any change to those tables changes it.
- **`convert`** opens `/vsizip/<zip>/<folder>` with the libgdal bundled in fiona's wheel,
  called through `ctypes` (Pyodide has no GDAL Python bindings), takes the layer as an Arrow
  stream (`OGR_L_GetArrowStream`, 10,000 features per batch) into pyarrow, and writes
  GeoParquet 1.1 (WKB `geometry`, zstd, the CRS as PROJJSON) batch by batch. GDAL reads only
  the entries that layer needs; no Python runs per feature.

Why these choices (measured in Pyodide 314.0.7, Chromium, on a 5.6 GiB geodatabase with a
1 GiB feature class among four 1.1 GiB decoys, plus GDAL's own ArcGIS-made test
geodatabases):

| approach | 1 GiB feature class |
|---|---|
| fiona, a Python dict per feature | about 7× slower than the Arrow stream (52 MB: 4.7 s vs 0.66 s) |
| GDAL Arrow stream through ctypes, geodatabase folder | 10–12 s, reads 1.08 GB of the 5.6 GiB |
| same, `/vsizip/` of a stored zip | 12–13 s |
| same, `/vsizip/` of a deflated zip (decompressed in wasm) | 19–20 s |
| zip entries decompressed by the browser (`DecompressionStream`) to OPFS, then mounted | 10 s + 11 s |
| native GDAL, same layer, for comparison | 6.2 s |

`/vsizip/` is the simplest of the fast options and needs no zip code of ours, so the adapter
uses it. The catalog parsing in `inspect` was checked against GDAL's feature counts on every
layer of two ArcGIS-made geodatabases (10.x: 37 layers, 9.2: 22 layers).

## Runtime services (`worker.js`)

### Read-ahead for WORKERFS

WORKERFS serves every read with one `FileReaderSync` call, about 1.5 ms each. GDAL reads a
geodatabase in a few bytes at a time: 80,000 reads, 130 s, for a 52 MB table. GDAL's own
`VSI_CACHE` brought that to 5–8 s. The worker now keeps up to 8 windows per open file: a
read inside a window is a copy; a miss at or just past a window's end (sequential reading)
fetches the next window at twice the size, up to 4 MB; any other miss fetches 64 KB.

This applies to every dataset, so it was measured on DuckDB too (a 438 MiB Parquet, 20 M rows):

| query | before | one 4 MB window | adaptive windows |
|---|---|---|---|
| `count(*)` | 0.13 s | 0.09 s | 0.09 s |
| group by over 3 columns | 18.6 s (6,202 reads) | **39.0 s (11 GB read)** | 6.7 s (282 reads) |
| `sum(x)` | 4.7 s | 1.6 s | 1.6 s |
| point lookup | 0.41 s | 0.21 s | 0.26 s |
| string group by | 7.0 s | 3.1 s | 3.4 s |
| gdb table, 1 GiB, GDAL | 130 s per 52 MB | 10.3 s | 12.5 s |

A single window thrashes when DuckDB alternates between column chunks; so does a window
that resets on a read straddling its end (GDAL: 133 s before that case counted as sequential).

### The ingest worker

Conversion runs in a separate worker in the `ingest` role: the same worker script, started
without the project, which loads the adapter's packages only when it has to convert. It is
terminated afterwards, so its heap (about 1 GiB for the large layer, from GDAL's batches)
and packages never burden the main worker's 4 GiB wasm heap. Cancel terminates it.

Handlers: `ingestSource` (mount the file, load the adapter source), `inspect`, `convert`.
`convert` posts `ingest-progress` messages (`phase`, `done`, `total`) as the adapter calls
`progress`.

### Output: OPFS, or a Blob

The output goes to the origin-private file system (OPFS) through a sync access handle, so it
never sits in memory, and the resulting `File` is mounted in the main worker like any
dataset. OPFS doubles as a **cache**: `blocks-datasets/<app>.<dataset>.<fingerprint>.data`
plus a `.json` written last (the entry only counts once that exists and the sizes agree).
One conversion is kept per dataset; a new one replaces the old.

`file://` pages (a built app) have no OPFS (`SecurityError`, tested in Chromium in both
private and normal profiles). There the output is a Blob assembled from 32 MB parts:

| Blob from parts, read back in a worker | up to 1 GB | 2 GB | 3–4 GB |
|---|---|---|---|
| normal profile (a real browser) | ok | ok | ok (spilled to disk) |
| private context (Playwright's default) | ok | fails | fails |

1 MB parts failed intermittently at 1 GB; 16–64 MB parts did not. So a built app converts on every visit (no cache), and a private
window caps the output at about 1 GB. An OPFS write that comes up short (quota) raises
"storage is full" rather than producing a truncated file.

## The data row (`app/runtime.js`, `app/modals.js`, `app/report.js`)

The Data modal's row (and the dataset's card on the page of the node that reads it) shows, for a format dataset:

- before: `needed: parcels.gdb.zip (116.4 KB), a zipped file geodatabase; its Parcels feature class is converted to GeoParquet in your browser (2,000 features), about 12 s` (the text after the file comes from `describe`);
- during: a progress bar, the phase (`Starting the converter`, `Reading the file's index`, `Loading the converter's packages (fiona, pyarrow)`, `Opening the data`, `Converting 412,000 of 820,000 features`), the time left, and **Cancel**;
- after: `original · 77.6 KB · provided by you · 2,000 features, converted in 11.8 s, cached for next time`, or `converted earlier (cached)`; errors show the adapter's message, e.g. `no feature class 'Parcels' in Data.gdb (have: Roads, Sites)`.

**Time left.** Before any feature is converted, the estimate is
`12 s + table bytes / 20 MB/s`: worker start and package loading, then the measured
conversion rate. Once features arrive it is `(total − done) / rate`, the rate measured since
conversion began. On the 1 GiB layer from a 5.3 GiB deflated zip in the app, the up-front
estimate was 44 s with the first constants (now retuned), the run took 66 s, and the running estimate read
48, 42, 33, 27, 21, 16, 10 and 4.5 s at 6 s intervals.

`state.data[name].progress` holds the same numbers for agents (`get_overview`), and
`window.protoApp.cancelIngest(name)` cancels.

## Identity and verification

- A format dataset's `sha256` is the adapter's fingerprint, so the baseline records it and
  `code_sha` covers it; `code_sha` also includes the sha256 of each adapter's source, so
  changing the adapter makes baselines stale, as changing a node does.
- A file the viewer provides counts as the original when its fingerprint matches; anything
  else makes runs "modified", exactly as for swapped plain datasets. No whole-file hash is
  needed, which matters at 10 GB.
- Plain datasets are now hashed in a stream, remembered by size and mtime (the dev server
  loads an app on every data request; before, every load read each file whole into memory).

## Builds

- A format dataset with `inline: false` is always picked by the viewer, in linked builds
  too: copying a multi-GB zip from the dev server into the page would put it in a Blob, which
  a private context cannot hold. Linked apps still start at once on later visits, because
  the cache is looked up by the recorded fingerprint before asking for the file.
- With `inline: true` (small sources), the zip is served (linked) or embedded (inline) and
  converted the same way.
- Inline builds embed the adapter's packages' wheels; the parcels app is 69 MB.
- `harvest` provides user datasets through the file input in `blocks run` and `baseline`
  (linked) as it already did in `blocks build`.

## CLI

`blocks convert SRC DEST --format gdb-zip -o layer=Parcels` runs the same adapter in the same
ingest worker in headless Chromium (a persistent profile, for the storage quota) and saves
the output, printing progress. Plain `blocks convert SRC DEST` still uses DuckDB.

## Example

`studies/parcels`: a synthetic `Parcels.gdb` zipped the way Windows zips it (a `Parcels.gdb/`
folder entry, deflate, data descriptors), three feature classes, and an app `land-use` that
summarises area and assessed value per land use with pyarrow and shapely.

The fixture was written with fiona in Pyodide. Pyodide's GDAL 3.8 cannot write lines or
polygons with a transverse Mercator CRS ("Point outside of projection domain"; points and
Web Mercator work), so it uses EPSG:3857. Reading is unaffected.

## Tests

`tests/test_adapters.py`: `inspect` (counts, fingerprint stable across re-zipping, error
messages, several geodatabases in one zip), spec and build integration, the dev server's
ETag; in the browser, conversion with progress events, the run matching the baseline, the
cache on reload, re-zipped and partial files, cancel, `blocks convert`, `blocks run` and
`blocks build` from `file://`.

## Not done / open

- A zip made by Windows Explorer itself was not available; the fixture reproduces its
  layout (folder entry, deflate, data descriptors). Non-ASCII folder names in old (CP437)
  zips: `zipfile` and GDAL's `/vsizip/` both decode CP437, untested.
- Compressed file geodatabases (ArcGIS "Compress", CDF) are not readable by GDAL 3.8; they
  fail in `convert` with GDAL's message, not in `inspect`.
- No layer chooser: `layer:` is required, because the nodes depend on the layer's
  schema. `inspect` lists the layers in errors.
- Cache eviction is one conversion per dataset and origin; nothing removes a dataset's
  conversion when the app drops it.
- The conversion rate constants come from one machine; they only shape the estimate before
  the first batch.
