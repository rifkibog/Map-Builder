'use client';

const LAYER_TYPES = {
  BUILDING_FINAL: 'building_final',
  GOOGLE: 'google',
  ONEGEO: 'onegeo'
};

const LAYER_NAMES = {
  [LAYER_TYPES.BUILDING_FINAL]: 'Building Final',
  [LAYER_TYPES.GOOGLE]: 'Google',
  [LAYER_TYPES.ONEGEO]: 'OneGeo'
};

export default function InfoPanel({ stats, zoom, showBuildings, activeLayers = {} }) {
  const activeLayerList = Object.entries(activeLayers)
    .filter(([_, isActive]) => isActive)
    .map(([layerType]) => layerType);

  return (
    <div className="info-panel">
      <h2>🏗️ Building Viewer Indonesia</h2>
      <div className="stats">
        <div>
          <span className="label">Total Data: </span>
          <span>136,121,247 buildings</span>
        </div>
        <div>
          <span className="label">Mode: </span>
          <span>{stats.mode}</span>
        </div>
        <div>
          <span className="label">Visible: </span>
          <span>{stats.count.toLocaleString()}</span>
        </div>
        <div>
          <span className="label">Zoom: </span>
          <span>{zoom}</span>
        </div>
        
        {/* Active Layers */}
        <div className="active-layers">
          <div className="active-layers-title">Active Layers:</div>
          {activeLayerList.length > 0 ? (
            activeLayerList.map(layerType => (
              <span 
                key={layerType} 
                className={`layer-badge ${layerType.replace('_', '-')}`}
              >
                {LAYER_NAMES[layerType]}
              </span>
            ))
          ) : (
            <span style={{ fontSize: '10px', color: '#999' }}>No layers selected</span>
          )}
        </div>
        
        <div style={{ marginTop: '10px', fontSize: '10px', color: '#999' }}>
          {showBuildings 
            ? '🏠 Klik building untuk detail'
            : '⬡ Zoom in (≥14) untuk lihat building'}
        </div>
      </div>
    </div>
  );
}
