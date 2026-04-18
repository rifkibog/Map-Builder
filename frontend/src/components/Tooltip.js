'use client';

export default function Tooltip({ x, y, object, showBuildings }) {
  if (!object) return null;

  const style = {
    left: x + 10,
    top: y + 10
  };

  if (showBuildings) {
    return (
      <div className="tooltip" style={style}>
        <h3>🏠 Building Info</h3>
        <p>
          <span className="label">Desa: </span>
          <span className="value">{object.DESA || '-'}</span>
        </p>
        <p>
          <span className="label">Kecamatan: </span>
          <span className="value">{object.KECAMATAN || '-'}</span>
        </p>
        <p>
          <span className="label">Kabupaten: </span>
          <span className="value">{object.KABUPATEN || '-'}</span>
        </p>
        <p>
          <span className="label">Provinsi: </span>
          <span className="value">{object.PROVINSI || '-'}</span>
        </p>
        <hr style={{ margin: '8px 0', border: 'none', borderTop: '1px solid #eee' }} />
        <p>
          <span className="label">Luas: </span>
          <span className="value">{parseFloat(object.area_in_meters || 0).toFixed(1)} m²</span>
        </p>
        <p>
          <span className="label">Tinggi: </span>
          <span className="value">{parseFloat(object.ketinggian_meter || 0).toFixed(1)} m</span>
        </p>
      </div>
    );
  }

  return (
    <div className="tooltip" style={style}>
      <h3>⬡ H3 Cell</h3>
      <p>
        <span className="label">Buildings: </span>
        <span className="value">{(object.building_count || 0).toLocaleString()}</span>
      </p>
      <p>
        <span className="label">Avg Area: </span>
        <span className="value">{parseFloat(object.avg_area || 0).toFixed(1)} m²</span>
      </p>
    </div>
  );
}
