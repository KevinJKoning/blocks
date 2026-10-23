# Land use by area

The data step happens before the graph: choose the zipped geodatabase (`Parcels.gdb`
zipped on Windows) in the Data modal. The `gdb-zip` plugin reads only the `Parcels` feature
class from the zip, converts it to GeoParquet with GDAL in the browser (progress and time
left are shown), and mounts it at `data/parcels.parquet`. In a served app the conversion is
cached, so the next visit starts at once.

`areas` reads the GeoParquet with pyarrow and shapely: planar area in the layer's
coordinate system (Web Mercator here, so areas are inflated by about 1/cos²(latitude)), and
parcels below `min_area_m2` dropped as slivers. `summary` adds area and assessed value up
per land use.
