"""Every parcel's planar area, with slivers dropped.

Reads the Parcels layer (GeoParquet, converted from the zipped geodatabase) with pyarrow
and computes each polygon's area with shapely, in the layer's coordinate system. Parcels
smaller than `min_area_m2` are slivers left by digitizing and are dropped.
"""
import json
from typing import Annotated

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapely

from blocks import Note, Range, ui

SCHEMA = {
    "parcels": {"fields": [
        {"name": "LANDUSE", "type": "string", "description": "Land use class", "constraints": {"required": True}},
        {"name": "ASSESSED", "type": "number", "description": "Assessed value", "constraints": {"minimum": 0}},
        {"name": "geometry", "type": "binary", "description": "Parcel polygon (WKB)", "constraints": {"required": True}},
    ]},
}
METRICS = {"parcels": "parcels kept", "slivers_dropped": "slivers dropped"}


def areas(parcels, *, min_area_m2: Annotated[int, Range(0, 5000, 100), Note("parcels smaller than this are slivers")] = 1000):
    table = pq.read_table(parcels, columns=["LANDUSE", "ASSESSED", "geometry"])
    geo = json.loads(pq.read_schema(parcels).metadata[b"geo"])
    area = shapely.area(shapely.from_wkb(table["geometry"].to_numpy(zero_copy_only=False)))
    keep = area >= min_area_m2
    kept = pa.table({"land_use": pc.filter(table["LANDUSE"], pa.array(keep)),
                     "assessed": pc.filter(pc.fill_null(table["ASSESSED"], 0), pa.array(keep)),
                     "area_m2": pa.array(area[keep])})
    return {"table": kept, "parcels": int(keep.sum()), "slivers_dropped": int((~keep).sum()),
            "crs": (geo["columns"]["geometry"].get("crs") or {}).get("id", {}).get("code")}


def view(out):
    counts, edges = np.histogram(out["table"]["area_m2"].to_numpy(), bins=20)
    return [
        ui.metrics(),
        ui.markdown(f"Areas in EPSG:{out['crs']} square metres; {out['slivers_dropped']} slivers dropped."),
        ui.chart((edges[:-1] + edges[1:]) / 2, {"parcels": counts}, title="Parcels by area", x_label="area (m²)", id="areas"),
        ui.data(out["table"], title="Parcels kept", id="kept"),
    ]
