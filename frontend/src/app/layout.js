import './globals.css';
import { AuthProvider } from '../lib/AuthProvider';

export const metadata = {
  title: 'Building Viewer - 136M Buildings Indonesia',
  description: 'Web application untuk visualisasi 136 juta data building Indonesia',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
