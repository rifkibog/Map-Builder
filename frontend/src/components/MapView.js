'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
import Map, { NavigationControl } from 'react-map-gl/maplibre';
import DeckGL from '@deck.gl/react';
import { GeoJsonLayer } from '@deck.gl/layers';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import 'maplibre-gl/dist/maplibre-gl.css';
import InfoPanel from './InfoPanel';
import Tooltip from './Tooltip';
import Legend from './Legend';
import SearchCoords from './SearchCoords';

// Satellite basemap (free from ESRI)
const MAP_STYLE = {
  version: 8,
  sources: {
    'esri-satellite': {
      type: 'raster',
      tiles: [
        'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}'
      ],
      tileSize: 256,
      attribution: '© Esri'
    }
  },
  layers: [
    {
      id: 'esri-satellite-layer',
      type: 'raster',
      source: 'esri-satellite',
      minzoom: 0,
      maxzoom: 24
    }
  ]
};

const DEFAULT_CENTER = [117.0, -2.5];
const DEFAULT_ZOOM = 5;
const ZOOM_THRESHOLD_BUILDINGS = 14;
const MAX_BUILDINGS_VIEWPORT = 3000;

// Layer types configuration
const LAYER_TYPES = {
  BUILDING_FINAL: 'building_final',
  GOOGLE: 'google',
  ONEGEO: 'onegeo'
};

// Colors for each layer type (distinct from height legend colors)
const LAYER_COLORS = {
  // Building Final uses height-based colors (existing legend)
  [LAYER_TYPES.BUILDING_FINAL]: {
    HIGH: [255, 0, 100, 200],      // Pink/Magenta - tinggi > 10m
    MEDIUM: [255, 150, 0, 200],    // Orange - tinggi > 5m  
    LOW: [0, 200, 100, 200],       // Green - tinggi > 0m
    NO_HEIGHT: [0, 150, 255, 200]  // Blue - tidak ada data ketinggian
  },
  // Google layer - Cyan/Teal colors (berbeda dari legend ketinggian)
  [LAYER_TYPES.GOOGLE]: {
    FILL: [0, 200, 200, 180],      // Cyan
    STROKE: [0, 255, 255, 255]     // Bright Cyan
  },
  // OneGeo layer - Purple/Violet colors (berbeda dari legend ketinggian)
  [LAYER_TYPES.ONEGEO]: {
    FILL: [180, 100, 255, 180],    // Light Purple
    STROKE: [200, 150, 255, 255]   // Bright Purple
  }
};

const getH3Resolution = (zoom) => {
  if (zoom >= 14) return 9;
  if (zoom >= 12) return 8;
  if (zoom >= 10) return 7;
  if (zoom >= 8) return 6;
  return 5;
};

const parseWKT = (wkt) => {
  if (!wkt) return null;
  try {
    const match = wkt.match(/POLYGON\s*\(\(([^)]+)\)\)/i);
    if (match) {
      const coords = match[1].split(',').map(pair => {
        const [lng, lat] = pair.trim().split(/\s+/).map(Number);
        return [lng, lat];
      });
      return { type: 'Polygon', coordinates: [coords] };
    }
    const multiMatch = wkt.match(/MULTIPOLYGON\s*\(\(\(([^)]+)\)\)\)/i);
    if (multiMatch) {
      const coords = multiMatch[1].split(',').map(pair => {
        const [lng, lat] = pair.trim().split(/\s+/).map(Number);
        return [lng, lat];
      });
      return { type: 'Polygon', coordinates: [coords] };
    }
  } catch (e) {
    console.error('WKT parse error:', e);
  }
  return null;
};

const INITIAL_VIEW_STATE = {
  longitude: DEFAULT_CENTER[0],
  latitude: DEFAULT_CENTER[1],
  zoom: DEFAULT_ZOOM,
  pitch: 0,
  bearing: 0
};

export default function MapView() {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE);
  const [buildings, setBuildings] = useState([]);
  const [h3Cells, setH3Cells] = useState([]);
  const [loading, setLoading] = useState(false);
  const [tooltip, setTooltip] = useState(null);
  const [selectedBuilding, setSelectedBuilding] = useState(null);
  const [stats, setStats] = useState({ count: 0, mode: 'H3 Aggregation' });
  
  // Layer visibility state
  const [activeLayers, setActiveLayers] = useState({
    [LAYER_TYPES.BUILDING_FINAL]: true,
    [LAYER_TYPES.GOOGLE]: false,
    [LAYER_TYPES.ONEGEO]: false
  });
  
  const mapRef = useRef(null);
  const debounceRef = useRef(null);

  const showBuildings = viewState.zoom >= ZOOM_THRESHOLD_BUILDINGS;

  // Go to specific location
  const goToLocation = useCallback((lng, lat, zoom) => {
    setViewState(prev => ({
      ...prev,
      longitude: lng,
      latitude: lat,
      zoom: zoom
    }));
  }, []);

  // Go to specific location
  // Toggle layer visibility
  const toggleLayer = (layerType) => {
    setActiveLayers(prev => ({
      ...prev,
      [layerType]: !prev[layerType]
    }));
  };

  // Fetch buildings from API
  const fetchBuildingsData = async (bounds, layerType) => {
    try {
      const params = new URLSearchParams({
        min_lng: bounds.minLng,
        max_lng: bounds.maxLng,
        min_lat: bounds.minLat,
        max_lat: bounds.maxLat,
        limit: MAX_BUILDINGS_VIEWPORT,
        layer_type: layerType
      });
      
      const response = await fetch(`/api/buildings?${params}`);
      if (!response.ok) throw new Error('API error');
      return await response.json();
    } catch (error) {
      console.error(`Error fetching ${layerType}:`, error);
      return [];
    }
  };

  // Fetch H3 aggregation from API
  const fetchH3Data = async (bounds, resolution) => {
    try {
      const params = new URLSearchParams({
        min_lng: bounds.minLng,
        max_lng: bounds.maxLng,
        min_lat: bounds.minLat,
        max_lat: bounds.maxLat,
        resolution
      });
      
      const response = await fetch(`/api/h3?${params}`);
      if (!response.ok) throw new Error('API error');
      return await response.json();
    } catch (error) {
      console.error('Error fetching H3:', error);
      return [];
    }
  };

  // Get viewport bounds
  const getViewportBounds = useCallback(() => {
    const { longitude, latitude, zoom } = viewState;
    const latRange = 180 / Math.pow(2, zoom);
    const lngRange = 360 / Math.pow(2, zoom);
    return {
      minLng: longitude - lngRange,
      maxLng: longitude + lngRange,
      minLat: latitude - latRange,
      maxLat: latitude + latRange
    };
  }, [viewState]);

  // Load data based on zoom level and active layers
  const loadData = useCallback(async () => {
    setLoading(true);
    const bounds = getViewportBounds();
    
    try {
      if (showBuildings) {
        // Load buildings for each active layer
        const allBuildings = [];
        
        for (const [layerType, isActive] of Object.entries(activeLayers)) {
          if (isActive) {
            const data = await fetchBuildingsData(bounds, layerType);
            // Add layer type to each building for coloring
            const taggedData = data.map(b => ({ ...b, _layerType: layerType }));
            allBuildings.push(...taggedData);
          }
        }
        
        // Convert to GeoJSON features
        const features = allBuildings
          .map((b, idx) => {
            const geometry = parseWKT(b.geometry_wkt);
            if (!geometry) return null;
            return {
              type: 'Feature',
              id: idx,
              geometry,
              properties: { ...b }
            };
          })
          .filter(Boolean);
        
        setBuildings(features);
        setH3Cells([]);
        setStats({ count: features.length, mode: 'Individual Buildings' });
      } else {
        // H3 Aggregation mode
        const resolution = getH3Resolution(viewState.zoom);
        const data = await fetchH3Data(bounds, resolution);
        setH3Cells(data);
        setBuildings([]);
        const totalBuildings = data.reduce((sum, cell) => sum + (cell.building_count || 0), 0);
        setStats({ count: totalBuildings, mode: `H3 Aggregation (res ${resolution})` });
      }
    } catch (error) {
      console.error('Error loading data:', error);
    }
    
    setLoading(false);
  }, [showBuildings, viewState.zoom, activeLayers, getViewportBounds]);

  // Debounced data loading on view change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(loadData, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [loadData]);

  const onViewStateChange = useCallback(({ viewState: newViewState }) => {
    setViewState(newViewState);
  }, []);

  const onHover = useCallback((info) => {
    if (info.object) {
      const obj = info.object.properties || info.object;
      setTooltip({ x: info.x, y: info.y, object: obj });
    } else {
      setTooltip(null);
    }
  }, []);

  const onClick = useCallback((info) => {
    if (info.object) {
      const obj = info.object.properties || info.object;
      setSelectedBuilding(obj);
    } else {
      setSelectedBuilding(null);
    }
  }, []);

  // Get fill color based on layer type and building properties
  const getFillColor = (d) => {
    const props = d.properties || d;
    const layerType = props._layerType || LAYER_TYPES.BUILDING_FINAL;
    
    if (layerType === LAYER_TYPES.GOOGLE) {
      return LAYER_COLORS[LAYER_TYPES.GOOGLE].FILL;
    }
    
    if (layerType === LAYER_TYPES.ONEGEO) {
      return LAYER_COLORS[LAYER_TYPES.ONEGEO].FILL;
    }
    
    // Building Final - use height-based coloring
    const height = parseFloat(props.ketinggian_meter) || 0;
    if (height > 10) return LAYER_COLORS[LAYER_TYPES.BUILDING_FINAL].HIGH;
    if (height > 5) return LAYER_COLORS[LAYER_TYPES.BUILDING_FINAL].MEDIUM;
    if (height > 0) return LAYER_COLORS[LAYER_TYPES.BUILDING_FINAL].LOW;
    return LAYER_COLORS[LAYER_TYPES.BUILDING_FINAL].NO_HEIGHT;
  };

  // Get stroke color based on layer type
  const getStrokeColor = (d) => {
    const props = d.properties || d;
    const layerType = props._layerType || LAYER_TYPES.BUILDING_FINAL;
    
    if (selectedBuilding && props.uid === selectedBuilding.uid) {
      return [255, 255, 0, 255]; // Yellow highlight for selected
    }
    
    if (layerType === LAYER_TYPES.GOOGLE) {
      return LAYER_COLORS[LAYER_TYPES.GOOGLE].STROKE;
    }
    
    if (layerType === LAYER_TYPES.ONEGEO) {
      return LAYER_COLORS[LAYER_TYPES.ONEGEO].STROKE;
    }
    
    return [255, 255, 255, 200]; // White for Building Final
  };

  const layers = [
    // H3 Hexagon layer (when zoomed out)
    !showBuildings && new H3HexagonLayer({
      id: 'h3-layer',
      data: h3Cells,
      pickable: true,
      wireframe: false,
      filled: true,
      extruded: false,
      getHexagon: d => d.h3_cell,
      getFillColor: d => {
        const count = d.building_count || 0;
        if (count > 1000) return [255, 0, 0, 180];
        if (count > 500) return [255, 100, 0, 180];
        if (count > 100) return [255, 200, 0, 180];
        if (count > 50) return [100, 200, 100, 180];
        return [0, 150, 200, 150];
      },
      onHover,
      onClick
    }),
    
    // Buildings GeoJSON layer (when zoomed in)
    showBuildings && new GeoJsonLayer({
      id: 'buildings-layer',
      data: { type: 'FeatureCollection', features: buildings },
      pickable: true,
      stroked: true,
      filled: true,
      extruded: false,
      getFillColor,
      getLineColor: getStrokeColor,
      getLineWidth: d => {
        const props = d.properties || d;
        if (selectedBuilding && props.uid === selectedBuilding.uid) return 3;
        return 1;
      },
      lineWidthUnits: 'pixels',
      updateTriggers: {
        getFillColor: [activeLayers],
        getLineColor: [selectedBuilding?.uid, activeLayers],
        getLineWidth: [selectedBuilding?.uid]
      },
      onHover,
      onClick
    })
  ].filter(Boolean);

  return (
    <>
      <DeckGL
        viewState={viewState}
        onViewStateChange={onViewStateChange}
        controller={true}
        layers={layers}
        getCursor={({ isHovering }) => isHovering ? 'pointer' : 'grab'}
      >
        <Map ref={mapRef} mapStyle={MAP_STYLE}>
          <NavigationControl position="bottom-right" />
        </Map>
      </DeckGL>

      {/* Layer Selector Panel */}
      <div className="layer-selector">
        <h3>📍 Layer Selection</h3>
        <div className="layer-options">
          <label className={`layer-option ${activeLayers[LAYER_TYPES.BUILDING_FINAL] ? 'active' : ''}`}>
            <input
              type="checkbox"
              checked={activeLayers[LAYER_TYPES.BUILDING_FINAL]}
              onChange={() => toggleLayer(LAYER_TYPES.BUILDING_FINAL)}
            />
            <span className="layer-color" style={{ backgroundColor: 'rgba(0, 150, 255, 0.8)' }}></span>
            Building Final with Desa
          </label>
          
          <label className={`layer-option ${activeLayers[LAYER_TYPES.GOOGLE] ? 'active' : ''}`}>
            <input
              type="checkbox"
              checked={activeLayers[LAYER_TYPES.GOOGLE]}
              onChange={() => toggleLayer(LAYER_TYPES.GOOGLE)}
            />
            <span className="layer-color" style={{ backgroundColor: 'rgba(0, 200, 200, 0.8)' }}></span>
            Peta Google
          </label>
          
          <label className={`layer-option ${activeLayers[LAYER_TYPES.ONEGEO] ? 'active' : ''}`}>
            <input
              type="checkbox"
              checked={activeLayers[LAYER_TYPES.ONEGEO]}
              onChange={() => toggleLayer(LAYER_TYPES.ONEGEO)}
            />
            <span className="layer-color" style={{ backgroundColor: 'rgba(180, 100, 255, 0.8)' }}></span>
            Peta OneGeo
          </label>
        </div>
      </div>

      {/* Search Coordinates */}
      <SearchCoords onSearch={goToLocation} />

      <InfoPanel 
        stats={stats} 
        zoom={viewState.zoom.toFixed(1)}
        showBuildings={showBuildings}
        activeLayers={activeLayers}
      />
      
      {tooltip && !selectedBuilding && (
        <Tooltip 
          x={tooltip.x} 
          y={tooltip.y} 
          object={tooltip.object}
          showBuildings={showBuildings}
        />
      )}
      
      {selectedBuilding && (
        <div className="selected-building-panel">
          <button className="close-btn" onClick={() => setSelectedBuilding(null)}>×</button>
          <h3>🏠 Building Info</h3>
          <p><span className="label">Source:</span> <span className="value">{selectedBuilding.bf_source || selectedBuilding._layerType || '-'}</span></p>
          <p><span className="label">Building ID:</span> <span className="value" style={{fontSize: '9px'}}>{selectedBuilding.building_id || '-'}</span></p>
          <hr />
          <p><span className="label">Desa:</span> <span className="value">{selectedBuilding.DESA || '-'}</span></p>
          <p><span className="label">Kecamatan:</span> <span className="value">{selectedBuilding.KECAMATAN || '-'}</span></p>
          <p><span className="label">Kabupaten:</span> <span className="value">{selectedBuilding.KABUPATEN || '-'}</span></p>
          <p><span className="label">Provinsi:</span> <span className="value">{selectedBuilding.PROVINSI || '-'}</span></p>
          <hr />
          <p><span className="label">Luas:</span> <span className="value">{selectedBuilding.area_in_meters ? parseFloat(selectedBuilding.area_in_meters).toFixed(1) + ' m²' : 'N/A'}</span></p>
          <p><span className="label">Tinggi:</span> <span className="value">{selectedBuilding.ketinggian_meter ? parseFloat(selectedBuilding.ketinggian_meter).toFixed(1) + ' m' : 'N/A'}</span></p>
          <p><span className="label">OneGeo ID:</span> <span className="value" style={{fontSize: '9px'}}>{selectedBuilding.onegeo_id || '-'}</span></p>
        </div>
      )}
      
      <Legend showBuildings={showBuildings} activeLayers={activeLayers} />
      
      {loading && <div className="loading">Loading data...</div>}
      
      <div className="zoom-info">
        Zoom: {viewState.zoom.toFixed(1)} | {showBuildings ? ' 🏠 Buildings' : ' ⬡ H3 Cells'}
      </div>
    </>
  );
}
