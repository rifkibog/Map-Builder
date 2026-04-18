'use client';

// Layer types (same as MapView.js)
const LAYER_TYPES = {
  BUILDING_FINAL: 'building_final',
  GOOGLE: 'google',
  ONEGEO: 'onegeo'
};

export default function Legend({ showBuildings, activeLayers = {} }) {
  return (
    <div className="legend">
      <h4>Legend</h4>
      
      {showBuildings ? (
        <>
          {/* Building Final Height Legend - only show if Building Final is active */}
          {activeLayers[LAYER_TYPES.BUILDING_FINAL] && (
            <div className="legend-section">
              <div className="legend-title">📊 Ketinggian (Building Final)</div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(255, 0, 100, 0.8)' }}></span>
                <span>&gt; 10m (Tinggi)</span>
              </div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(255, 150, 0, 0.8)' }}></span>
                <span>5-10m (Sedang)</span>
              </div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(0, 200, 100, 0.8)' }}></span>
                <span>0-5m (Rendah)</span>
              </div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(0, 150, 255, 0.8)' }}></span>
                <span>No Height Data</span>
              </div>
            </div>
          )}
          
          {/* Google Layer Legend */}
          {activeLayers[LAYER_TYPES.GOOGLE] && (
            <div className="legend-section">
              <div className="legend-title">🗺️ Peta Google</div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(0, 200, 200, 0.8)', border: '2px solid cyan' }}></span>
                <span>Google Buildings</span>
              </div>
            </div>
          )}
          
          {/* OneGeo Layer Legend */}
          {activeLayers[LAYER_TYPES.ONEGEO] && (
            <div className="legend-section">
              <div className="legend-title">🌐 Peta OneGeo</div>
              <div className="legend-item">
                <span className="color-box" style={{ backgroundColor: 'rgba(180, 100, 255, 0.8)', border: '2px solid #c896ff' }}></span>
                <span>OneGeo Buildings</span>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="legend-section">
          <div className="legend-title">📊 Building Density</div>
          <div className="legend-item">
            <span className="color-box" style={{ backgroundColor: 'rgba(255, 0, 0, 0.7)' }}></span>
            <span>&gt; 1000</span>
          </div>
          <div className="legend-item">
            <span className="color-box" style={{ backgroundColor: 'rgba(255, 100, 0, 0.7)' }}></span>
            <span>500-1000</span>
          </div>
          <div className="legend-item">
            <span className="color-box" style={{ backgroundColor: 'rgba(255, 200, 0, 0.7)' }}></span>
            <span>100-500</span>
          </div>
          <div className="legend-item">
            <span className="color-box" style={{ backgroundColor: 'rgba(100, 200, 100, 0.7)' }}></span>
            <span>50-100</span>
          </div>
          <div className="legend-item">
            <span className="color-box" style={{ backgroundColor: 'rgba(0, 150, 200, 0.6)' }}></span>
            <span>&lt; 50</span>
          </div>
        </div>
      )}
    </div>
  );
}
