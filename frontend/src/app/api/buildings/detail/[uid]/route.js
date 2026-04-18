import { NextResponse } from 'next/server';

const API_KEY = process.env.API_KEY;
const BACKEND_URL = process.env.BACKEND_URL || 'https://building-viewer-api-1029375354934.asia-southeast1.run.app';

export async function GET(request, { params }) {
  try {
    const uid = params.uid;

    if (!uid) {
      return NextResponse.json(
        { error: 'Missing uid parameter' },
        { status: 400 }
      );
    }

    const backendUrl = `${BACKEND_URL}/api/buildings/detail/${uid}`;
    
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
