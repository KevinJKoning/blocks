"""Area and assessed value per land use: the answer."""
import numpy as np

from blocks import ui

METRICS = {
    "residential_area_share": {"label": "residential share", "goal": "max", "headline": True},
    "total_area_ha": {"label": "total area (ha)", "goal": "max", "headline": True},
    "value_per_ha": {"label": "value per ha", "goal": "max", "headline": True},
}


def summary(areas):
    t = areas["table"]
    uses = np.asarray(t["land_use"].to_pylist(), dtype=object)
    area, value = t["area_m2"].to_numpy(), t["assessed"].to_numpy()
    by_use = {u: {"parcels": int((uses == u).sum()), "area_ha": float(area[uses == u].sum() / 1e4),
                  "value": float(value[uses == u].sum())} for u in sorted(set(uses))}
    total_ha = float(area.sum() / 1e4)
    return {"total_area_ha": total_ha,
            "residential_area_share": by_use.get("residential", {}).get("area_ha", 0.0) / total_ha if total_ha else 0.0,
            "value_per_ha": float(value.sum() / total_ha) if total_ha else 0.0, "by_land_use": by_use}


def rows(out):
    return [{"land use": u, "parcels": v["parcels"], "area (ha)": round(v["area_ha"], 2), "assessed value": round(v["value"])}
            for u, v in sorted(out["by_land_use"].items(), key=lambda kv: -kv[1]["area_ha"])]


def view(out):
    return [ui.metrics(), ui.table(rows(out), title="By land use", id="by-use")]


def downloads(out):
    return [ui.file("land_use_summary.csv", rows(out), title="parcels, area and assessed value per land use")]
