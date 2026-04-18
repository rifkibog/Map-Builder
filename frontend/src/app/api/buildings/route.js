import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'https://building-viewer-api-1029375354934.asia-southeast1.run.app';

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  
  try {
    const backendUrl = `${BACKEND_URL}/api/buildings?${searchParams.toString()}`;
    console.log('Proxying buildings request to:', backendUrl);
    
    const response = await fetch(backendUrl);
    
    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Buildings proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch buildings data', details: error.message }, 
      { status: 500 }
    );
  }
}
