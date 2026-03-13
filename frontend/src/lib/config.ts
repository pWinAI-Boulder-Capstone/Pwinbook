/**
 * Runtime configuration for the frontend.
 * This allows the same Docker image to work in different environments.
 */

import { AppConfig, BackendConfigResponse } from '@/lib/types/config'

// Build timestamp for debugging - set at build time
const BUILD_TIME = new Date().toISOString()

let config: AppConfig | null = null
let configPromise: Promise<AppConfig> | null = null

const traceId = `cfg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

function traceHeaders(step: string): HeadersInit {
  return {
    'x-on-trace-id': traceId,
    'x-on-trace-step': step,
  }
}

/**
 * Get the API URL to use for requests.
 *
 * Priority:
 * 1. Runtime config from API server (/api/config endpoint)
 * 2. Environment variable (NEXT_PUBLIC_API_URL)
 * 3. Default fallback (same-origin proxy)
 */
export async function getApiUrl(): Promise<string> {
  // If we already have config, return it
  if (config) {
    return config.apiUrl
  }

  // If we're already fetching, wait for that
  if (configPromise) {
    const cfg = await configPromise
    return cfg.apiUrl
  }

  // Start fetching config
  configPromise = fetchConfig()
  const cfg = await configPromise
  return cfg.apiUrl
}

/**
 * Get the full configuration.
 */
export async function getConfig(): Promise<AppConfig> {
  if (config) {
    return config
  }

  if (configPromise) {
    return await configPromise
  }

  configPromise = fetchConfig()
  return await configPromise
}

/**
 * Fetch configuration from the API or use defaults.
 */
async function fetchConfig(): Promise<AppConfig> {
  console.log('🔧 [Config] Starting configuration detection...')
  console.log('🔧 [Config] Build time:', BUILD_TIME)
  console.log('🔧 [Config] Trace ID:', traceId)

  // STEP 1: Try to get runtime config from Next.js server-side endpoint
  // This allows API_URL to be set at runtime (not baked into build)
  // Note: Endpoint is at /config (not /api/config) to avoid reverse proxy conflicts
  let runtimeApiUrl: string | null = null
  try {
    console.log('🔧 [Config] Attempting to fetch runtime config from /config endpoint...')
    const runtimeResponse = await fetch('/config', {
      cache: 'no-store',
      headers: traceHeaders('runtime-config-endpoint'),
    })
    if (runtimeResponse.ok) {
      const runtimeData = await runtimeResponse.json()
      runtimeApiUrl = runtimeData.apiUrl
      console.log('✅ [Config] Runtime API URL from server:', runtimeApiUrl)
    } else {
      console.log('⚠️ [Config] Runtime config endpoint returned status:', runtimeResponse.status)
    }
  } catch (error) {
    console.log('⚠️ [Config] Could not fetch runtime config:', error)
  }

  // STEP 2: Fallback to build-time environment variable
  const envApiUrl = process.env.NEXT_PUBLIC_API_URL
  console.log('🔧 [Config] NEXT_PUBLIC_API_URL from build:', envApiUrl || '(not set)')

  // STEP 3: Safe default - same-origin proxy via Next.js rewrites
  // This prevents implicit cross-port calls (e.g. :5055) unless explicitly configured.
  const defaultApiUrl = ''
  console.log('🔧 [Config] Default mode: same-origin proxy (/api/* via Next.js rewrites)')

  // Priority: Runtime config > Build-time env var > Smart default
  const baseUrl = runtimeApiUrl ?? envApiUrl ?? defaultApiUrl
  console.log('🔧 [Config] Final base URL to try:', baseUrl || '(empty -> same-origin)')
  console.log('🔧 [Config] Selection priority: runtime=' + (runtimeApiUrl ? '✅' : '❌') +
              ', build-time=' + (envApiUrl ? '✅' : '❌') +
              ', smart-default=' + (!runtimeApiUrl && !envApiUrl ? '✅' : '❌'))

  try {
    console.log('🔧 [Config] Fetching backend config from:', `${baseUrl}/api/config`)
    // Try to fetch runtime config from backend API
    const response = await fetch(`${baseUrl}/api/config`, {
      cache: 'no-store',
      headers: traceHeaders('backend-config-endpoint'),
    })

    if (response.ok) {
      const data: BackendConfigResponse = await response.json()
      config = {
        apiUrl: baseUrl, // Use baseUrl from runtime-config (Python no longer returns this)
        version: data.version || 'unknown',
        buildTime: BUILD_TIME,
        latestVersion: data.latestVersion || null,
        hasUpdate: data.hasUpdate || false,
        dbStatus: data.dbStatus, // Can be undefined for old backends
      }
      console.log('✅ [Config] Successfully loaded API config:', config)
      return config
    } else {
      // Don't log error here - ConnectionGuard will display it
      throw new Error(`API config endpoint returned status ${response.status}`)
    }
  } catch (error) {
    // Don't log error here - ConnectionGuard will display it with proper UI
    throw error
  }
}

/**
 * Reset the configuration cache (useful for testing).
 */
export function resetConfig(): void {
  config = null
  configPromise = null
}
