import { NextRequest, NextResponse } from 'next/server'

function getInternalApiUrl(): string {
  return process.env.INTERNAL_API_URL || 'http://localhost:5055'
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()

    const internalApiUrl = getInternalApiUrl()
    const backendResponse = await fetch(`${internalApiUrl}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    })

    const data = await backendResponse.json().catch(() => null)

    if (!backendResponse.ok) {
      return NextResponse.json(
        data || { success: false, message: 'Authentication failed' },
        { status: backendResponse.status }
      )
    }

    const token: string | undefined = data?.token

    // If backend auth is disabled, it returns token="not-required".
    // Still set a cookie so middleware/UI stays consistent.
    if (token) {
      const response = NextResponse.json(data, { status: 200 })
      response.cookies.set({
        name: 'open_notebook_auth',
        value: token,
        httpOnly: true,
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
        maxAge: 60 * 60 * 24 * 7, // 7 days
      })
      return response
    }

    return NextResponse.json(data, { status: 200 })
  } catch (error) {
    console.error('[site-auth/login] error:', error)
    return NextResponse.json(
      { success: false, message: 'Invalid request' },
      { status: 400 }
    )
  }
}
