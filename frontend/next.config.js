/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    serverComponentsExternalPackages: ['undici'],
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://building-viewer-api-1029375354934.asia-southeast1.run.app/api/:path*',
      },
    ];
  },
}

module.exports = nextConfig
