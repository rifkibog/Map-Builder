from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.database import bigquery as db

router = APIRouter(prefix="/api/buildings", tags=["buildings"])


@router.get("/viewport")
def get_buildings_viewport(
    min_lng: float = Query(..., description="Minimum longitude"),
    min_lat: float = Query(..., description="Minimum latitude"),
    max_lng: float = Query(..., description="Maximum longitude"),
    max_lat: float = Query(..., description="Maximum latitude"),
    limit: int = Query(10000, le=50000, description="Max buildings to return")
):
    """
    Get buildings within viewport bounding box.
    Use this for zoom levels 14+ when showing individual buildings.
    """
    try:
        buildings = db.get_buildings_by_viewport(min_lng, min_lat, max_lng, max_lat, limit)
        return {
            "count": len(buildings), 
            "buildings": buildings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/h3")
def get_buildings_by_h3(
    h3_indexes: str = Query(..., description="Comma-separated H3 indexes"),
    limit: int = Query(10000, le=50000, description="Max buildings to return")
):
    """
    Get buildings by H3 cell indexes.
    Use this for efficient spatial queries.
    """
    try:
        h3_list = [h.strip() for h in h3_indexes.split(",")]
        buildings = db.get_buildings_by_h3(h3_list, limit)
        return {
            "count": len(buildings), 
            "buildings": buildings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/aggregation")
def get_h3_aggregation(
    min_lng: float = Query(..., description="Minimum longitude"),
    min_lat: float = Query(..., description="Minimum latitude"),
    max_lng: float = Query(..., description="Maximum longitude"),
    max_lat: float = Query(..., description="Maximum latitude"),
    resolution: int = Query(7, ge=5, le=9, description="H3 resolution (5-9)")
):
    """
    Get aggregated building counts per H3 cell.
    Use this for zoom levels < 14 to show heatmap/hexagons.
    """
    try:
        aggregation = db.get_h3_aggregation(min_lng, min_lat, max_lng, max_lat, resolution)
        return {
            "count": len(aggregation),
            "resolution": resolution,
            "cells": aggregation
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail/{uid}")
def get_building_detail(uid: str):
    """Get detailed information for a single building"""
    try:
        building = db.get_building_detail(uid)
        if not building:
            raise HTTPException(status_code=404, detail="Building not found")
        return building
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/desa/{id_desa}")
def get_desa_stats(id_desa: int):
    """Get building statistics for a specific desa"""
    try:
        stats = db.get_stats_by_desa(id_desa)
        if not stats:
            raise HTTPException(status_code=404, detail="Desa not found")
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
def search_buildings(
    provinsi: Optional[str] = Query(None, description="Filter by provinsi"),
    kabupaten: Optional[str] = Query(None, description="Filter by kabupaten"),
    kecamatan: Optional[str] = Query(None, description="Filter by kecamatan"),
    desa: Optional[str] = Query(None, description="Filter by desa"),
    limit: int = Query(1000, le=10000, description="Max buildings to return")
):
    """Search buildings by location hierarchy"""
    try:
        buildings = db.search_buildings(provinsi, kabupaten, kecamatan, desa, limit)
        return {
            "count": len(buildings),
            "buildings": buildings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
