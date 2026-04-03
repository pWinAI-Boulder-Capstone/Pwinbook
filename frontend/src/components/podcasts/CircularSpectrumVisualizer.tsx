'use client'

import { useEffect, useRef, type RefObject } from 'react'

const BARS = 80
const RINGS = 3

interface CircularSpectrumVisualizerProps {
  analyserRef: RefObject<AnalyserNode | null>
  isPlaying: boolean
  /** CSS px diameter of the canvas (HiDPI scaled internally) */
  size?: number
  className?: string
}

export function CircularSpectrumVisualizer({
  analyserRef,
  isPlaying,
  size = 340,
  className,
}: CircularSpectrumVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dataRef = useRef(new Uint8Array(256))
  const rafRef = useRef(0)
  const layoutRef = useRef({ dpr: 0, w: 0, h: 0 })

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx2 = canvas.getContext('2d')
    if (!ctx2) return

    const draw = (t: number) => {
      const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
      const w = size
      const h = size
      const lay = layoutRef.current
      if (lay.dpr !== dpr || lay.w !== w || lay.h !== h) {
        lay.dpr = dpr
        lay.w = w
        lay.h = h
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        ctx2.setTransform(dpr, 0, 0, dpr, 0, 0)
      }

      const cx = w / 2
      const cy = h / 2
      const analyser = analyserRef.current
      let bufferLength = 0
      if (analyser) {
        bufferLength = analyser.frequencyBinCount
        if (dataRef.current.length !== bufferLength) {
          dataRef.current = new Uint8Array(bufferLength)
        }
        analyser.getByteFrequencyData(dataRef.current)
      }

      ctx2.clearRect(0, 0, w, h)

      const baseR = Math.min(w, h) * 0.34
      const grad = ctx2.createLinearGradient(cx - baseR, cy - baseR, cx + baseR, cy + baseR)
      grad.addColorStop(0, 'rgba(219, 39, 119, 0.95)')
      grad.addColorStop(0.45, 'rgba(244, 114, 182, 0.85)')
      grad.addColorStop(1, 'rgba(251, 191, 36, 0.9)')

      const now = t * 0.001

      for (let ring = 0; ring < RINGS; ring++) {
        ctx2.beginPath()
        const ringBoost = 1 + ring * 0.07
        const binBias = ring * 4

        for (let i = 0; i <= BARS; i++) {
          const frac = i / BARS
          const angle = frac * Math.PI * 2 - Math.PI / 2

          let mag = 0
          if (analyser && bufferLength > 0 && isPlaying) {
            const bin = Math.min(
              bufferLength - 1,
              Math.floor(frac * bufferLength * 0.55) + binBias
            )
            mag = dataRef.current[bin]! / 255
            mag = Math.pow(mag, 0.65)
          } else {
            mag =
              0.12 +
              0.06 * Math.sin(now * 2.2 + frac * Math.PI * 4 + ring) +
              0.04 * Math.sin(now * 3.5 + i * 0.15)
          }

          const r = baseR * ringBoost * (0.88 + mag * 0.42 + ring * 0.04)
          const x = cx + Math.cos(angle) * r
          const y = cy + Math.sin(angle) * r
          if (i === 0) ctx2.moveTo(x, y)
          else ctx2.lineTo(x, y)
        }
        ctx2.closePath()
        ctx2.strokeStyle = grad
        ctx2.lineWidth = 2.2 - ring * 0.35
        ctx2.lineJoin = 'round'
        ctx2.shadowColor = 'rgba(219, 39, 119, 0.45)'
        ctx2.shadowBlur = isPlaying ? 14 - ring * 3 : 6
        ctx2.stroke()
        ctx2.shadowBlur = 0
      }

      rafRef.current = requestAnimationFrame(draw)
    }

    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [analyserRef, isPlaying, size])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      aria-hidden
    />
  )
}
