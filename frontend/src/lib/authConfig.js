// Konfigurasi Authentication
export const authConfig = {
  // Domain yang diizinkan
  allowedDomains: ['gmail.com'],
  
  // Whitelist email yang diizinkan
  whitelist: [
    'wakeupwise16@gmail.com',
    'b0g4r4@gmail.com',
    'eko.atmaja@gmail.com',
  ],
  
  // Jika true, hanya email di whitelist yang bisa akses
  // Jika false, semua email dari domain yang diizinkan bisa akses
  useWhitelist: true
};

// Function untuk cek apakah email diizinkan
export function isEmailAllowed(email) {
  if (!email) return false;
  
  const domain = email.split('@')[1];
  
  // Cek domain dulu
  if (!authConfig.allowedDomains.includes(domain)) {
    return false;
  }
  
  // Jika whitelist aktif, cek apakah email ada di whitelist
  if (authConfig.useWhitelist) {
    return authConfig.whitelist.includes(email.toLowerCase());
  }
  
  // Jika whitelist tidak aktif, semua email dari domain yang diizinkan bisa akses
  return true;
}
