import { NextRequest, NextResponse } from 'next/server'

/**
 * Runtime Configuration Endpoint
 *
 * This endpoint provides server-side environment variables to the client at runtime.
 * This solves the NEXT_PUBLIC_* limitation where variables are baked into the build.
 *
 * Environment Variables:
 * - API_URL: Where the browser/client should make API requests (public/external URL)
 * - INTERNAL_API_URL: Where Next.js server-side should proxy API requests (internal URL)
 *   Default: http://localhost:5055 (used by Next.js rewrites in next.config.ts)
 *
 * Why two different variables?
 * - API_URL: Used by browser clients, can be https://your-domain.com or http://server-ip:5055
 * - INTERNAL_API_URL: Used by Next.js rewrites for server-side proxying, typically http://localhost:5055
 *
 * Auto-detection logic for API_URL:
 * 1. If API_URL env var is set, use it (explicit override)
 * 2. Otherwise, use same-origin proxying (empty base URL)
 *
 * This allows the same Docker image to work in different deployment scenarios.
 */
export async function GET(request: NextRequest) {
  const traceId = request.headers.get('x-on-trace-id') || 'none'
  const traceStep = request.headers.get('x-on-trace-step') || 'unknown'
  const hostHeader = request.headers.get('host') || 'unknown'
  const forwardedFor = request.headers.get('x-forwarded-for') || 'unknown'
  const userAgent = request.headers.get('user-agent') || 'unknown'

  console.log(
    `[runtime-config] request traceId=${traceId} step=${traceStep} host=${hostHeader} xff=${forwardedFor} ua=${userAgent}`,
  )

  // Priority 1: Check if API_URL is explicitly set
  const envApiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL

  if (envApiUrl) {
    console.log(`[runtime-config] traceId=${traceId} resolved source=env apiUrl=${envApiUrl}`)
    return NextResponse.json({
      apiUrl: envApiUrl,
    })
  }

  // Priority 2: same-origin proxy mode via Next.js rewrites (/api/*)
  // Returning an empty base URL avoids direct browser calls to host:5055.
  console.log(`[runtime-config] traceId=${traceId} resolved source=same-origin-proxy apiUrl=(empty)`)
  return NextResponse.json({
    apiUrl: '',
  })
}
