'use client';

import { useState } from 'react';
import { useAuth } from '../lib/AuthProvider';

export default function UserMenu() {
  const { user, logout } = useAuth();
  const [showMenu, setShowMenu] = useState(false);

  if (!user) return null;

  return (
    <div className="user-menu">
      <button 
        className="user-button"
        onClick={() => setShowMenu(!showMenu)}
      >
        {user.photoURL ? (
          <img src={user.photoURL} alt={user.displayName} className="user-avatar" />
        ) : (
          <div className="user-avatar-placeholder">
            {user.displayName?.[0] || user.email?.[0] || '?'}
          </div>
        )}
      </button>
      
      {showMenu && (
        <div className="user-dropdown">
          <div className="user-info">
            <p className="user-name">{user.displayName}</p>
            <p className="user-email">{user.email}</p>
          </div>
          <hr />
          <button className="logout-button" onClick={logout}>
            🚪 Logout
          </button>
        </div>
      )}
    </div>
  );
}
