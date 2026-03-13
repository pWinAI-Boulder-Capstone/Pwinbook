import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const shouldLogProxyDebug = process.env.OPEN_NOTEBOOK_PROXY_DEBUG === 'true'

  if (shouldLogProxyDebug && (pathname.startsWith('/api') || pathname === '/config')) {
    console.log(
      `[FRONTEND REQUEST] ${request.method} ${pathname}${request.nextUrl.search} host=${request.headers.get('host') || 'unknown'} origin=${request.headers.get('origin') || 'unknown'} referer=${request.headers.get('referer') || 'unknown'}`,
    )
  }

  // When API password auth is enabled, also gate the UI site-wide.
  // This prevents anonymous users from loading pages and spamming actions.
  const authEnabled = Boolean(process.env.OPEN_NOTEBOOK_PASSWORD || process.env.FRONTEND_AUTH_ENABLED)

  // Always allow auth/config and API endpoints.
  if (
    pathname.startsWith('/api') ||
    pathname.startsWith('/site-auth') ||
    pathname === '/login' ||
    pathname === '/config'
  ) {
    return NextResponse.next()
  }

  if (authEnabled) {
    const tokenCookie = request.cookies.get('open_notebook_auth')?.value
    if (!tokenCookie) {
      const loginUrl = request.nextUrl.clone()
      loginUrl.pathname = '/login'
      loginUrl.searchParams.set('next', pathname + request.nextUrl.search)
      return NextResponse.redirect(loginUrl)
    }
  }

  // Redirect root to notebooks
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/notebooks', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!site-auth|_next/static|_next/image|favicon.ico).*)',
  ],
}