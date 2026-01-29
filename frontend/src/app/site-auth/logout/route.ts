import { NextResponse } from 'next/server'

export async function POST() {
  const response = NextResponse.json({ success: true }, { status: 200 })
  response.cookies.set({
    name: 'open_notebook_auth',
    value: '',
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 0,
  })
  return response
}
