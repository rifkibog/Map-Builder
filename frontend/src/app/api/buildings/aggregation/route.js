import { NextResponse } from 'next/server';

const API_KEY = process.env.API_KEY;
const BACKEND_URL = process.env.BACKEND_URL || 'https://building-viewer-api-1029375354934.asia-southeast1.run.app';

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const min_lng = searchParams.get('min_lng');
    const min_lat = searchParams.get('min_lat');
    const max_lng = searchParams.get('max_lng');
    const max_lat = searchParams.get('max_lat');
    const resolution = searchParams.get('resolution') || '7';

    if (!min_lng || !min_lat || !max_lng || !max_lat) {
      return NextResponse.json(
        { error: 'Missing required parameters' },
        { status: 400 }
      );
    }

    const backendUrl = `${BACKEND_URL}/api/buildings/aggregation?min_lng=${min_lng}&min_lat=${min_lat}&max_lng=${max_lng}&max_lat=${max_lat}&resolution=${resolution}`;
    
    const response = await fetch(backendUrl, {
      headers: {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json'
      }
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json(
        { error: 'Backend error', details: error },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error('Proxy error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
