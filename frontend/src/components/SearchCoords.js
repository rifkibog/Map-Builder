'use client';
import { useState } from 'react';

export default function SearchCoords({ onSearch }) {
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');

  const handleSearch = (e) => {
    e.preventDefault();
    const latitude = parseFloat(lat);
    const longitude = parseFloat(lng);
    
    if (isNaN(latitude) || isNaN(longitude)) {
      alert('Masukkan koordinat yang valid');
      return;
    }
    
    if (latitude < -11 || latitude > 6 || longitude < 95 || longitude > 141) {
      alert('Koordinat di luar wilayah Indonesia');
      return;
    }
    
    onSearch(longitude, latitude, 18);
  };

  return (
    <div className="search-coords">
      <h3>🔍 Search Location</h3>
      <form onSubmit={handleSearch}>
        <div className="coord-inputs">
          <div className="coord-field">
            <label>Latitude</label>
            <input
              type="text"
              placeholder="-6.2088"
              value={lat}
              onChange={(e) => setLat(e.target.value)}
            />
          </div>
          <div className="coord-field">
            <label>Longitude</label>
            <input
              type="text"
              placeholder="106.8456"
              value={lng}
              onChange={(e) => setLng(e.target.value)}
            />
          </div>
        </div>
        <button type="submit" className="search-btn">Go</button>
      </form>
    </div>
  );
}
