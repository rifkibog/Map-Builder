"""BigQuery database operations for building data with layer type support"""
import math
from google.cloud import bigquery
from ..config import settings

# Use deploy project for client, but query data project
client = bigquery.Client(project=settings.GCP_PROJECT)

def clean_float(value):
    """Convert NaN/Infinity to None for JSON serialization"""
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def clean_record(record):
    """Clean a record dict, converting NaN/Infinity to None"""
    cleaned = {}
    for key, value in record.items():
        if isinstance(value, float):
            cleaned[key] = clean_float(value)
        else:
            cleaned[key] = value
    return cleaned

def get_buildings_by_viewport(min_lng, max_lng, min_lat, max_lat, limit=5000, layer_type='building_final'):
    """Get buildings within viewport bounds, filtered by layer type."""
    
    table_prefix = f"`{settings.BQ_PROJECT}.{settings.BQ_DATASET}"
    
    if layer_type == 'google':
        query = f"""
        SELECT 
            uid,
            building_id,
            CAST(centroid_long AS FLOAT64) as centroid_long,
            CAST(centroid_lat AS FLOAT64) as centroid_lat,
            CAST(area_in_meters AS FLOAT64) as area_in_meters,
            geometry_wkt,
            bf_source,
            confidence,
            CAST(NULL AS FLOAT64) as ketinggian_meter,
            CAST(NULL AS STRING) as onegeo_id,
            CAST(NULL AS STRING) as DESA,
            CAST(NULL AS STRING) as KECAMATAN,
            CAST(NULL AS STRING) as KABUPATEN,
            CAST(NULL AS STRING) as PROVINSI
        FROM {table_prefix}.{settings.BQ_TABLE_GOOGLE}`
        WHERE CAST(centroid_long AS FLOAT64) BETWEEN {min_lng} AND {max_lng}
        AND CAST(centroid_lat AS FLOAT64) BETWEEN {min_lat} AND {max_lat}
        LIMIT {limit}
        """
    elif layer_type == 'onegeo':
        query = f"""
        SELECT 
            uid,
            string_field_3 as building_id,
            CAST(double_field_1 AS FLOAT64) as centroid_long,
            CAST(double_field_2 AS FLOAT64) as centroid_lat,
            CAST(double_field_5 AS FLOAT64) as area_in_meters,
            string_field_0 as geometry_wkt,
            string_field_6 as bf_source,
            CAST(NULL AS FLOAT64) as confidence,
            CAST(double_field_4 AS FLOAT64) as ketinggian_meter,
            uid as onegeo_id,
            CAST(NULL AS STRING) as DESA,
            CAST(NULL AS STRING) as KECAMATAN,
            CAST(NULL AS STRING) as KABUPATEN,
            CAST(NULL AS STRING) as PROVINSI
        FROM {table_prefix}.{settings.BQ_TABLE_ONEGEO}`
        WHERE CAST(double_field_1 AS FLOAT64) BETWEEN {min_lng} AND {max_lng}
        AND CAST(double_field_2 AS FLOAT64) BETWEEN {min_lat} AND {max_lat}
        LIMIT {limit}
        """
    else:
        query = f"""
        SELECT 
            uid,
            building_id,
            CAST(centroid_long AS FLOAT64) as centroid_long,
            CAST(centroid_lat AS FLOAT64) as centroid_lat,
            CAST(area_in_meters AS FLOAT64) as area_in_meters,
            geometry_wkt,
            bf_source,
            confidence,
            CAST(ketinggian_meter AS FLOAT64) as ketinggian_meter,
            onegeo_id,
            DESA,
            KECAMATAN,
            KABUPATEN,
            PROVINSI
        FROM {table_prefix}.{settings.BQ_TABLE_BUILDINGS}`
        WHERE CAST(centroid_long AS FLOAT64) BETWEEN {min_lng} AND {max_lng}
        AND CAST(centroid_lat AS FLOAT64) BETWEEN {min_lat} AND {max_lat}
        LIMIT {limit}
        """
    
    try:
        result = client.query(query).to_dataframe()
        records = result.to_dict('records')
        return [clean_record(r) for r in records]
    except Exception as e:
        print(f"Error querying {layer_type}: {e}")
        return []


def get_h3_aggregation(min_lng, max_lng, min_lat, max_lat, resolution=7):
    """Get H3 aggregation for the viewport with resolution-based truncation"""
    
    # Calculate viewport size
    lng_range = max_lng - min_lng
    lat_range = max_lat - min_lat
    area_degrees = lng_range * lat_range
    
    # For very large areas, return empty to avoid timeout
    # Resolution 5 covers ~252 km², max area ~100 degrees²
    max_area_by_resolution = {
        4: 200,  # Very zoomed out - limit to ~200 sq degrees
        5: 100,  # Country level - limit to ~100 sq degrees  
        6: 25,   # Province level
        7: 10,   # City level
        8: 2,    # District level
        9: 0.5   # Neighborhood level
    }
    
    max_area = max_area_by_resolution.get(resolution, 10)
    
    if area_degrees > max_area:
        print(f"Area too large ({area_degrees:.1f} sq deg) for resolution {resolution}, max allowed: {max_area}")
        return []
    
    # Use H3 SUBSTR to get parent cell at desired resolution
    # H3 index format allows truncation for lower resolutions
    h3_column = "h3_index"
    
    # For resolutions lower than stored (assuming stored at res 9),
    # we need to use BigQuery H3 functions or pre-aggregated tables
    # For now, we'll filter and aggregate at query time
    
    query = f"""
    SELECT 
        SUBSTR({h3_column}, 1, 15) as h3_cell,
        COUNT(*) as building_count,
        AVG(CAST(area_in_meters AS FLOAT64)) as avg_area,
        AVG(CAST(ketinggian_meter AS FLOAT64)) as avg_height
    FROM `{settings.BQ_PROJECT}.{settings.BQ_DATASET}.{settings.BQ_TABLE_BUILDINGS}`
    WHERE CAST(centroid_long AS FLOAT64) BETWEEN {min_lng} AND {max_lng}
    AND CAST(centroid_lat AS FLOAT64) BETWEEN {min_lat} AND {max_lat}
    AND {h3_column} IS NOT NULL
    GROUP BY h3_cell
    LIMIT 10000
    """
    
    try:
        job_config = bigquery.QueryJobConfig(
            timeout_ms=30000  # 30 second timeout
        )
        result = client.query(query, job_config=job_config).to_dataframe()
        records = result.to_dict('records')
        return [clean_record(r) for r in records]
    except Exception as e:
        print(f"Error querying H3 aggregation: {e}")
        return []


def search_buildings(provinsi=None, kabupaten=None, kecamatan=None, desa=None, limit=1000):
    """Search buildings by location hierarchy"""
    conditions = []
    if provinsi:
        conditions.append(f"PROVINSI = '{provinsi}'")
    if kabupaten:
        conditions.append(f"KABUPATEN = '{kabupaten}'")
    if kecamatan:
        conditions.append(f"KECAMATAN = '{kecamatan}'")
    if desa:
        conditions.append(f"DESA = '{desa}'")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    query = f"""
    SELECT 
        uid, building_id, 
        CAST(centroid_long AS FLOAT64) as centroid_long, 
        CAST(centroid_lat AS FLOAT64) as centroid_lat,
        CAST(area_in_meters AS FLOAT64) as area_in_meters,
        CAST(ketinggian_meter AS FLOAT64) as ketinggian_meter,
        geometry_wkt, bf_source, onegeo_id,
        DESA, KECAMATAN, KABUPATEN, PROVINSI
    FROM `{settings.BQ_PROJECT}.{settings.BQ_DATASET}.{settings.BQ_TABLE_BUILDINGS}`
    WHERE {where_clause}
    LIMIT {limit}
    """
    
    try:
        result = client.query(query).to_dataframe()
        records = result.to_dict('records')
        return [clean_record(r) for r in records]
    except Exception as e:
        print(f"Error searching buildings: {e}")
        return []


def get_stats_by_desa(id_desa):
    """Get statistics for a desa"""
    query = f"""
    SELECT 
        COUNT(*) as total_buildings,
        AVG(CAST(area_in_meters AS FLOAT64)) as avg_area,
        AVG(CAST(ketinggian_meter AS FLOAT64)) as avg_height
    FROM `{settings.BQ_PROJECT}.{settings.BQ_DATASET}.{settings.BQ_TABLE_BUILDINGS}`
    WHERE ID_DESA = '{id_desa}'
    """
    
    try:
        result = client.query(query).to_dataframe().to_dict('records')
        if result:
            return clean_record(result[0])
        return None
    except Exception as e:
        print(f"Error getting stats: {e}")
        return None
