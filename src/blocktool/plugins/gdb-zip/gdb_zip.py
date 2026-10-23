"""gdb-zip: one feature class of an Esri file geodatabase, from a zip of its folder, to GeoParquet.

The zip is what Windows "Send to > Compressed (zipped) folder" makes: a `Name.gdb/` folder
with the geodatabase's files in it (any folder depth, deflate or stored, Zip64). Only the
entries this feature class needs are read: the catalog, the `GDB_*` system tables and the
feature class's own table. `inspect` reads the zip index and two small entries with the
standard library; `convert` reads the table through GDAL (`/vsizip/`, the libgdal bundled
with fiona, called through ctypes) as an Arrow stream and writes GeoParquet (WKB) batch by
batch, so neither the layer nor the output is ever held whole in memory.
"""
from __future__ import annotations

import hashlib
import json
import struct
import zipfile

NAME = "gdb-zip"
VERSION = 1
PACKAGES = ["fiona", "pyarrow"]
OUTPUT = "data.parquet"
UNIT = "features"
OPTIONS = {"layer": "the feature class to load (required)",
           "gdb": "the .gdb folder inside the zip, when it holds more than one"}
BATCH = 10000   # features per Arrow batch: progress granularity and peak memory


def describe(opts: dict) -> str:
    """What the viewer is asked for, completing "needed: FILE, …"."""
    return f"a zipped file geodatabase; its {opts['layer']} feature class is converted to GeoParquet in your browser"


def check_options(opts: dict) -> dict:
    unknown = set(opts) - set(OPTIONS)
    if unknown:
        raise ValueError(f"{NAME}: unknown option(s) {sorted(unknown)} (have: {', '.join(OPTIONS)})")
    if not isinstance(opts.get("layer"), str) or not opts["layer"]:
        raise ValueError(f"{NAME}: `layer:` (the feature class name) is required")
    if "gdb" in opts and not isinstance(opts["gdb"], str):
        raise ValueError(f"{NAME}: `gdb:` must be the folder name of a .gdb inside the zip")
    return {k: opts[k] for k in OPTIONS if k in opts}


# -- the geodatabase catalog (GDB_SystemCatalog, a00000001.gdbtable) --------------------------
# Field types and layouts follow the OpenFileGDB format notes; only those the catalog uses.

def _varuint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return v, i


def _fields(t):
    (off,) = struct.unpack_from("<q", t, 32)
    i = off + 12
    (n,) = struct.unpack_from("<h", t, i)
    i += 2
    out = []
    for _ in range(n):
        ln = t[i]
        name = t[i + 1:i + 1 + 2 * ln].decode("utf-16-le")
        i += 1 + 2 * ln
        i += 1 + 2 * t[i]   # alias
        ty = t[i]
        i += 1
        nullable = False
        if ty == 4:                         # string: width, flags, optional default
            i += 4
            fl = t[i]
            i += 1
            nullable = bool(fl & 1)
            if fl & 4:
                dl, i = _varuint(t, i)
                i += dl
        elif ty == 6:                       # object id
            i += 2
        elif ty in (10, 11, 12):            # GUID, GlobalID, XML
            fl = t[i + 1]
            i += 2
            nullable = bool(fl & 1)
        elif ty in (0, 1, 2, 3, 5, 13):     # numbers and dates: width, flags, optional default
            fl = t[i + 1]
            i += 2
            nullable = bool(fl & 1)
            if fl & 4:
                i += 1 + t[i]
        else:
            raise ValueError(f"unexpected field type {ty} in the geodatabase catalog")
        out.append((name, ty, nullable))
    return out


def catalog(table: bytes, index: bytes) -> dict:
    """{table name: file stem 'aXXXXXXXX'}: the row number is the table number."""
    fields = _fields(table)
    nrows, osz = struct.unpack_from("<ii", index, 8)
    nnull = sum(1 for f in fields if f[2])
    out = {}
    for k in range(nrows):
        o = int.from_bytes(index[16 + k * osz:16 + (k + 1) * osz], "little")
        if not o:
            continue   # deleted row
        i = o + 4
        nb = table[i:i + (nnull + 7) // 8]
        i += (nnull + 7) // 8
        row, ni = {}, 0
        for name, ty, nullable in fields:
            if ty == 6:
                continue
            if nullable:
                isnull = nb[ni // 8] >> (ni % 8) & 1
                ni += 1
                if isnull:
                    row[name] = None
                    continue
            if ty == 4:
                ln, i = _varuint(table, i)
                row[name] = table[i:i + ln].decode("utf-8")
                i += ln
            elif ty in (12,):
                ln, i = _varuint(table, i)
                i += ln
            else:
                i += {0: 2, 1: 4, 2: 4, 3: 8, 5: 8, 13: 8, 10: 16, 11: 16}[ty]
        if row.get("Name"):
            out[row["Name"]] = f"a{k + 1:08x}"
    return out


def _gdb_folder(z: zipfile.ZipFile, want: str | None) -> str:
    """The folder (with trailing /) of the .gdb inside the zip."""
    found = sorted({n[:-len("a00000001.gdbtable")] for n in z.namelist() if n.endswith("a00000001.gdbtable")
                    and (n == "a00000001.gdbtable" or n.endswith("/a00000001.gdbtable"))})
    if not found:
        raise ValueError("this zip holds no file geodatabase (no a00000001.gdbtable inside)")
    names = [f.rstrip("/").rsplit("/", 1)[-1] or "(top level)" for f in found]
    if want:
        hits = [f for f, n in zip(found, names) if n == want]
        if not hits:
            raise ValueError(f"no geodatabase {want!r} in this zip (have: {', '.join(names)})")
        return hits[0]
    if len(found) > 1:
        raise ValueError(f"this zip holds {len(found)} geodatabases ({', '.join(names)}); choose one with `gdb:`")
    return found[0]


def inspect(path: str, opts: dict) -> dict:
    """Fingerprint and size of the feature class, from the zip index and the catalog only.

    The fingerprint covers the entries `convert` reads (name, size and CRC-32 from the zip
    index), the layer, and this adapter's NAME and VERSION: the same geodatabase zipped
    again, with another tool or another compression, has the same fingerprint."""
    opts = check_options(opts)
    with zipfile.ZipFile(path) as z:
        folder = _gdb_folder(z, opts.get("gdb"))
        cat = catalog(z.read(folder + "a00000001.gdbtable"), z.read(folder + "a00000001.gdbtablx"))
        layers = sorted(n for n in cat if not n.startswith("GDB_"))
        layer = opts["layer"]
        if layer not in layers:
            raise ValueError(f"no feature class {layer!r} in {folder.rstrip('/') or 'the zip'} (have: {', '.join(layers) or 'none'})")
        keep = {v for k, v in cat.items() if k.startswith("GDB_")} | {cat[layer]}
        entries = sorted((i.filename[len(folder):], i.file_size, i.CRC) for i in z.infolist()
                         if i.filename.startswith(folder) and "/" not in i.filename[len(folder):]
                         and i.filename[len(folder):].split(".")[0] in keep)
        try:
            table = z.getinfo(folder + cat[layer] + ".gdbtable")
        except KeyError:
            raise ValueError(f"the zip lacks {cat[layer]}.gdbtable, the table of {layer!r} (an incomplete copy?)") from None
        with z.open(table) as f:
            head = f.read(8)
        (features,) = struct.unpack_from("<I", head, 4)   # valid rows, from the table header
    fp = hashlib.sha256(json.dumps({"adapter": NAME, "version": VERSION, "layer": layer, "entries": entries},
                                   sort_keys=True).encode()).hexdigest()
    return {"fingerprint": fp, "gdb": folder.rstrip("/"), "layer": layer, "layers": layers, "table": cat[layer],
            "total": features, "unit": UNIT, "bytes": table.file_size, "compressed": table.compress_size,
            "deflated": table.compress_type == zipfile.ZIP_DEFLATED}


# -- conversion (Pyodide; GDAL through ctypes) -------------------------------------------------

_GEOM = {1: "Point", 2: "LineString", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon",
         7: "GeometryCollection"}


def _gdal():
    import ctypes
    import glob
    import os
    import fiona   # noqa: F401  loads libgdal and its dependencies, registers the drivers
    libs = os.path.join(os.path.dirname(os.path.dirname(fiona.__file__)), "fiona.libs")
    found = sorted(glob.glob(os.path.join(libs, "libgdal*.so*")))
    if not found:
        raise RuntimeError(f"libgdal not found in {libs}")
    g = ctypes.CDLL(found[0])
    p, s, i = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    for name, res, args in [("GDALOpenEx", p, [s, ctypes.c_uint, p, p, p]), ("GDALClose", None, [p]),
                            ("GDALDatasetGetLayerByName", p, [p, s]), ("OGR_L_GetArrowStream", i, [p, p, p]),
                            ("OGR_L_GetSpatialRef", p, [p]), ("OGR_L_GetGeomType", i, [p]),
                            ("OSRExportToPROJJSON", i, [p, ctypes.POINTER(p), p]), ("VSIFree", None, [p]),
                            ("CPLGetLastErrorMsg", s, []), ("CPLErrorReset", None, [])]:
        f = getattr(g, name)
        f.restype, f.argtypes = res, args
    return g


def _projjson(g, lyr):
    import ctypes
    srs = g.OGR_L_GetSpatialRef(lyr)
    if not srs:
        return None
    out = ctypes.c_void_p()
    if g.OSRExportToPROJJSON(srs, ctypes.byref(out), None) != 0 or not out.value:
        return None
    try:
        return json.loads(ctypes.string_at(out.value).decode())
    finally:
        g.VSIFree(out)


def convert(path: str, opts: dict, out, progress) -> dict:
    """Write the feature class as GeoParquet (WKB `geometry`, zstd) to the binary file `out`."""
    import ctypes
    import pyarrow as pa
    import pyarrow.parquet as pq
    info = inspect(path, opts)
    total = info["total"]
    progress(0, total, "opening")
    g = _gdal()
    g.CPLErrorReset()
    src = f"/vsizip/{path}/{info['gdb']}" if info["gdb"] else f"/vsizip/{path}"
    ds = g.GDALOpenEx(src.encode(), 0x04, None, None, None)   # GDAL_OF_VECTOR
    if not ds:
        raise RuntimeError(f"GDAL could not open the geodatabase: {(g.CPLGetLastErrorMsg() or b'').decode()}")
    try:
        lyr = g.GDALDatasetGetLayerByName(ds, info["layer"].encode())
        if not lyr:
            raise RuntimeError(f"GDAL has no layer {info['layer']!r}")
        stream = ctypes.create_string_buffer(64)   # struct ArrowArrayStream: five pointers
        options = (ctypes.c_char_p * 2)(f"MAX_FEATURES_IN_BATCH={BATCH}".encode(), None)
        if not g.OGR_L_GetArrowStream(lyr, ctypes.addressof(stream), options):
            raise RuntimeError(f"GDAL could not stream the layer: {(g.CPLGetLastErrorMsg() or b'').decode()}")
        reader = pa.RecordBatchReader._import_from_c(ctypes.addressof(stream))
        geom = next((f.name for f in reader.schema
                     if (f.metadata or {}).get(b"ARROW:extension:name") == b"ogc.wkb"), None)
        fields = [pa.field("geometry", pa.binary()) if f.name == geom else f.remove_metadata() for f in reader.schema]
        gtype = _GEOM.get(g.OGR_L_GetGeomType(lyr) % 1000)
        meta = {"version": "1.1.0", "primary_column": "geometry",
                "columns": {"geometry": {"encoding": "WKB", "geometry_types": [gtype] if gtype else [],
                                         **({"crs": _projjson(g, lyr)} if geom else {})}}}
        schema = pa.schema(fields, metadata={b"geo": json.dumps(meta).encode()} if geom else None)
        done = 0
        progress(0, total, "converting")
        with pq.ParquetWriter(pa.PythonFile(out, mode="w"), schema, compression="zstd") as w:
            for b in reader:
                w.write_batch(pa.RecordBatch.from_arrays(
                    [c.cast(pa.binary()) if n == geom else c for n, c in zip(reader.schema.names, b.columns)], schema=schema))
                done += b.num_rows
                progress(done, total, "converting")
        del reader
    finally:
        g.GDALClose(ds)
    progress(done, total, "done")
    return {"rows": done, "columns": schema.names, "layer": info["layer"], "geometry_type": gtype}
