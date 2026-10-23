"""blocks.schema: what a dataset should hold, and whether it does.

A node declares the data it reads with a module-level SCHEMA = {dataset: schema}, a
subset of Frictionless Table Schema
(https://specs.frictionlessdata.io/table-schema/). Two places run this module:
  check(value)              natively, when an app is loaded (stdlib only at module level):
                            validates a declaration and returns it normalized
  validate(path, schema)    in the page's worker (Pyodide), once the dataset is mounted:
                            what the data holds and where it breaks the schema
"""
from __future__ import annotations

TYPES = ("string", "number", "integer", "boolean", "date", "datetime", "time", "binary", "any")
CONSTRAINTS = ("required", "unique", "minimum", "maximum", "enum", "pattern", "minLength", "maxLength")
FIELD_KEYS = ("name", "type", "title", "description", "constraints", "unit")
# DuckDB column types each schema type accepts (by prefix).
DUCK = {
    "string": ("VARCHAR",),
    "number": ("DOUBLE", "FLOAT", "DECIMAL", "REAL", "HUGEINT", "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "UBIGINT",
               "UINTEGER", "USMALLINT", "UTINYINT"),
    "integer": ("HUGEINT", "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT"),
    "boolean": ("BOOLEAN",),
    "date": ("DATE",),
    "datetime": ("TIMESTAMP",),
    "time": ("TIME",),
    "binary": ("BLOB", "GEOMETRY"),
}
TABLE_EXT = (".parquet", ".csv", ".tsv", ".json", ".ndjson", ".jsonl")


def check(value) -> dict:
    """The declared schema, normalized: {fields: [...], primaryKey: [...]}."""
    if not isinstance(value, dict) or not isinstance(value.get("fields"), list) or not value["fields"]:
        raise ValueError("want {fields: [{name, type, ...}, ...]}")
    unknown = set(value) - {"fields", "primaryKey", "description"}
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)}")
    fields, names = [], set()
    for f in value["fields"]:
        if not isinstance(f, dict) or not f.get("name"):
            raise ValueError(f"field {f!r}: needs a name")
        name = str(f["name"])
        if name in names:
            raise ValueError(f"field {name} is declared twice")
        names.add(name)
        bad = set(f) - set(FIELD_KEYS)
        if bad:
            raise ValueError(f"field {name}: unknown keys {sorted(bad)}")
        typ = f.get("type", "any")
        if typ not in TYPES:
            raise ValueError(f"field {name}: type {typ!r} is not one of {', '.join(TYPES)}")
        cons = f.get("constraints") or {}
        bad = set(cons) - set(CONSTRAINTS)
        if bad:
            raise ValueError(f"field {name}: unknown constraints {sorted(bad)}")
        for k in ("minimum", "maximum"):
            if k in cons and not isinstance(cons[k], (int, float)):
                raise ValueError(f"field {name}: {k} must be a number")
        if "enum" in cons and not isinstance(cons["enum"], list):
            raise ValueError(f"field {name}: enum must be a list")
        fields.append({"name": name, "type": typ, "title": f.get("title") or "", "description": f.get("description") or "",
                       "unit": f.get("unit") or "", "constraints": dict(cons)})
    pk = value.get("primaryKey") or []
    pk = [pk] if isinstance(pk, str) else list(pk)
    for k in pk:
        if k not in names:
            raise ValueError(f"primaryKey {k!r} is not a field")
    return {"fields": fields, "primaryKey": pk, "description": value.get("description") or ""}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def validate(path: str, schema: dict) -> dict:
    """Check the table at `path` (relative to the app) against `schema`. Returns
    {rows, columns, fields: [{name, type, found, ok, nulls, min, max, problems}], extra,
    problems, ok}; a problem names the rule and how many rows break it."""
    import os
    import duckdb
    if os.path.isdir(path) or not path.lower().endswith(TABLE_EXT):
        return {"ok": None, "problems": [f"{path} is not one table file ({', '.join(TABLE_EXT)}); not checked"],
                "fields": [], "columns": [], "extra": [], "rows": None}
    db = duckdb.connect()
    src = f"(SELECT * FROM {_lit(path)})"
    cols = [(r[0], r[1]) for r in db.execute(f"DESCRIBE SELECT * FROM {_lit(path)}").fetchall()]
    types = dict(cols)
    rows = db.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    out_fields, problems = [], []
    for f in schema["fields"]:
        name, typ, cons = f["name"], f["type"], f["constraints"]
        res = {"name": name, "type": typ, "found": types.get(name), "problems": [], "nulls": None, "min": None, "max": None}
        if name not in types:
            res["problems"].append("missing column")
        else:
            c, duck = _q(name), types[name]
            if typ != "any" and not duck.upper().startswith(DUCK.get(typ, ())):
                res["problems"].append(f"type {duck}, not {typ}")
            nan = f" OR isnan({c})" if duck.upper().startswith(("DOUBLE", "FLOAT", "REAL")) else ""
            res["nulls"] = db.execute(f"SELECT count(*) FROM {src} WHERE {c} IS NULL{nan}").fetchone()[0]
            if typ in ("number", "integer", "date", "datetime", "time", "string") and not duck.upper().startswith(("BLOB", "GEOMETRY")):
                lo, hi = db.execute(f"SELECT min({c}), max({c}) FROM {src} WHERE NOT ({c} IS NULL{nan})").fetchone()
                res["min"], res["max"] = (lo, hi) if typ != "string" else (None, None)
            checks = []
            if cons.get("required") and res["nulls"]:
                res["problems"].append(f"required: {res['nulls']:,} empty")
            if "minimum" in cons:
                checks.append((f"{c} < {_lit(cons['minimum'])}", f"below minimum {cons['minimum']}"))
            if "maximum" in cons:
                checks.append((f"{c} > {_lit(cons['maximum'])}", f"above maximum {cons['maximum']}"))
            if "enum" in cons:
                checks.append((f"{c} NOT IN ({', '.join(_lit(v) for v in cons['enum'])})", "not one of enum"))
            if "pattern" in cons:
                checks.append((f"NOT regexp_full_match(CAST({c} AS VARCHAR), {_lit(cons['pattern'])})", f"not matching {cons['pattern']}"))
            if "minLength" in cons:
                checks.append((f"length(CAST({c} AS VARCHAR)) < {int(cons['minLength'])}", f"shorter than {cons['minLength']}"))
            if "maxLength" in cons:
                checks.append((f"length(CAST({c} AS VARCHAR)) > {int(cons['maxLength'])}", f"longer than {cons['maxLength']}"))
            for cond, what in checks:
                try:
                    n = db.execute(f"SELECT count(*) FROM {src} WHERE {c} IS NOT NULL AND ({cond})").fetchone()[0]
                except duckdb.Error as e:
                    res["problems"].append(f"{what}: not checked ({str(e).splitlines()[0]})")
                    continue
                if n:
                    res["problems"].append(f"{what}: {n:,} rows")
            if cons.get("unique"):
                n = db.execute(f"SELECT count(*) - count(DISTINCT {c}) FROM {src} WHERE {c} IS NOT NULL").fetchone()[0]
                if n:
                    res["problems"].append(f"unique: {n:,} duplicates")
        res["ok"] = not res["problems"]
        out_fields.append(res)
    if schema.get("primaryKey"):
        keys = ", ".join(_q(k) for k in schema["primaryKey"] if k in types)
        if keys:
            n = db.execute(f"SELECT count(*) - count(DISTINCT ({keys})) FROM {src}").fetchone()[0]
            if n:
                problems.append(f"primaryKey {', '.join(schema['primaryKey'])}: {n:,} duplicates")
    db.close()
    declared = {f["name"] for f in schema["fields"]}
    extra = [n for n, _ in cols if n not in declared]
    ok = not problems and all(f["ok"] for f in out_fields)
    return {"rows": rows, "columns": [{"name": n, "type": t} for n, t in cols], "fields": out_fields,
            "extra": extra, "problems": problems, "ok": ok}
