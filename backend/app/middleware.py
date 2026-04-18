from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time
from app.config import settings


# In-memory rate limit storage (use Redis in production for multi-instance)
rate_limit_storage = defaultdict(list)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate API Key in request header"""
    
    async def dispatch(self, request: Request, call_next):
        # Skip API key check if disabled
        if not settings.API_KEY_ENABLED:
            return await call_next(request)
        
        # Skip for health check and docs
        skip_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json"]
        if request.url.path in skip_paths:
            return await call_next(request)
        
        # Check API key in header
        api_key = request.headers.get("X-API-Key")
        
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "Missing API Key. Include 'X-API-Key' header."}
            )
        
        if api_key != settings.API_KEY:
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid API Key"}
            )
        
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit requests per IP"""
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting if disabled
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        
        # Skip for health check
        if request.url.path in ["/", "/health"]:
            return await call_next(request)
        
        # Get client IP
        client_ip = request.client.host
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        
        # Current timestamp
        now = time.time()
        window_start = now - settings.RATE_LIMIT_WINDOW
        
        # Clean old requests
        rate_limit_storage[client_ip] = [
            ts for ts in rate_limit_storage[client_ip] 
            if ts > window_start
        ]
        
        # Check rate limit
        if len(rate_limit_storage[client_ip]) >= settings.RATE_LIMIT_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Maximum {settings.RATE_LIMIT_REQUESTS} requests per {settings.RATE_LIMIT_WINDOW} seconds",
                    "retry_after": int(settings.RATE_LIMIT_WINDOW - (now - rate_limit_storage[client_ip][0]))
                }
            )
        
        # Record request
        rate_limit_storage[client_ip].append(now)
        
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(
            settings.RATE_LIMIT_REQUESTS - len(rate_limit_storage[client_ip])
        )
        response.headers["X-RateLimit-Reset"] = str(int(window_start + settings.RATE_LIMIT_WINDOW))
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response
