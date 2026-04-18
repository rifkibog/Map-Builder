'use client';

import dynamic from 'next/dynamic';
import { useAuth } from '../lib/AuthProvider';
import LoginPage from '../components/LoginPage';
import UserMenu from '../components/UserMenu';

const MapView = dynamic(() => import('../components/MapView'), {
  ssr: false,
  loading: () => <div className="loading">Loading map...</div>
});

export default function Home() {
  const { user, loading } = useAuth();

  // Tampilkan loading saat cek auth
  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner"></div>
        <p>Loading...</p>
      </div>
    );
  }

  // Jika belum login, tampilkan halaman login
  if (!user) {
    return <LoginPage />;
  }

  // Jika sudah login, tampilkan map
  return (
    <main className="map-container">
      <MapView />
      <UserMenu />
    </main>
  );
}
