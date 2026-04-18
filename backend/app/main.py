"""FastAPI main application with layer type support"""
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from .config import settings
from .database.bigquery import (
    get_buildings_by_viewport,
    get_h3_aggregation,
    search_buildings,
    get_stats_by_desa
)

app = FastAPI(
    title="Building Viewer API",
    description="API for visualizing 136M buildings in Indonesia",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Building Viewer API v2.0",
        "total_buildings": 136121247,
        "layers": ["building_final", "google", "onegeo"]
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/buildings")
async def get_buildings(
    min_lng: float = Query(..., description="Minimum longitude"),
    max_lng: float = Query(..., description="Maximum longitude"),
    min_lat: float = Query(..., description="Minimum latitude"),
    max_lat: float = Query(..., description="Maximum latitude"),
    limit: int = Query(5000, le=10000, description="Maximum buildings to return"),
    layer_type: str = Query("building_final", description="Layer type: building_final, google, or onegeo")
):
    """Get buildings within viewport bounds."""
    valid_layers = ["building_final", "google", "onegeo"]
    if layer_type not in valid_layers:
        raise HTTPException(status_code=400, detail=f"Invalid layer_type. Must be one of: {valid_layers}")
    
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="Invalid bounds")
    
    buildings = get_buildings_by_viewport(min_lng, max_lng, min_lat, max_lat, limit=limit, layer_type=layer_type)
    return buildings


@app.get("/api/h3")
async def get_h3(
    min_lng: float = Query(..., description="Minimum longitude"),
    max_lng: float = Query(..., description="Maximum longitude"),
    min_lat: float = Query(..., description="Minimum latitude"),
    max_lat: float = Query(..., description="Maximum latitude"),
    resolution: int = Query(7, ge=4, le=9, description="H3 resolution")
):
    """Get H3 aggregation for viewport"""
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="Invalid bounds")
    
    h3_data = get_h3_aggregation(min_lng, max_lng, min_lat, max_lat, resolution)
    return h3_data


@app.get("/api/search")
async def search(
    provinsi: Optional[str] = Query(None, description="Province name"),
    kabupaten: Optional[str] = Query(None, description="Regency/City name"),
    kecamatan: Optional[str] = Query(None, description="District name"),
    desa: Optional[str] = Query(None, description="Village name"),
    limit: int = Query(1000, le=5000, description="Maximum results")
):
    """Search buildings by location hierarchy"""
    if not any([provinsi, kabupaten, kecamatan, desa]):
        raise HTTPException(status_code=400, detail="At least one search parameter required")
    
    buildings = search_buildings(provinsi, kabupaten, kecamatan, desa, limit)
    return buildings


@app.get("/api/stats/{id_desa}")
async def get_desa_stats(id_desa: str):
    """Get statistics for a specific desa"""
    stats = get_stats_by_desa(id_desa)
    if not stats:
        raise HTTPException(status_code=404, detail="Desa not found")
    return stats


@app.get("/api/layers")
async def get_layers():
    """Get available layer types"""
    return {
        "layers": [
            {"id": "building_final", "name": "Building Final with Desa", "color": [0, 150, 255, 200]},
            {"id": "google", "name": "Peta Google", "color": [0, 200, 200, 180]},
            {"id": "onegeo", "name": "Peta OneGeo", "color": [180, 100, 255, 180]}
        ]
    }
