import React, { useEffect, useRef } from 'react'

interface AudioVisualizerProps {
  stream: MediaStream | null
  isActive: boolean
  className?: string
}

export const AudioVisualizer: React.FC<AudioVisualizerProps> = ({ stream, isActive, className }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>()
  const analyserRef = useRef<AnalyserNode | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)

  useEffect(() => {
    if (isActive && stream && canvasRef.current) {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      const source = audioContext.createMediaStreamSource(stream)
      const analyser = audioContext.createAnalyser()
      
      analyser.fftSize = 512
      source.connect(analyser)
      
      analyserRef.current = analyser
      audioContextRef.current = audioContext

      const bufferLength = analyser.frequencyBinCount
      const dataArray = new Uint8Array(bufferLength)
      const canvas = canvasRef.current
      const canvasCtx = canvas.getContext('2d')

      // Set canvas size to match element size for crisp rendering
      const updateSize = () => {
        if (canvas) {
          const rect = canvas.getBoundingClientRect()
          canvas.width = rect.width * window.devicePixelRatio
          canvas.height = rect.height * window.devicePixelRatio
        }
      }
      
      updateSize()
      window.addEventListener('resize', updateSize)
      
      const draw = () => {
        if (!canvasCtx || !canvas) return

        animationRef.current = requestAnimationFrame(draw)
        analyser.getByteFrequencyData(dataArray)

        const width = canvas.width
        const height = canvas.height

        canvasCtx.clearRect(0, 0, width, height)

        // Use frequency data for bar visualizer
        analyser.getByteFrequencyData(dataArray)

        // Human voice is mostly below 4kHz. With 44.1kHz sample rate,
        // focus on the first 40% of the spectrum to remove silent high frequencies.
        const effectiveBufferLength = Math.floor(bufferLength * 0.4)

        // Responsive bar count: fewer bars on smaller screens for cleaner look
        // Calculate based on actual canvas width (in CSS pixels, not device pixels)
        const cssWidth = width / window.devicePixelRatio
        let totalBars: number
        let barSpacingBase: number

        if (cssWidth < 200) {
          // Very small screens (mobile)
          totalBars = 16
          barSpacingBase = 2
        } else if (cssWidth < 300) {
          // Small screens
          totalBars = 24
          barSpacingBase = 2.5
        } else if (cssWidth < 400) {
          // Medium screens
          totalBars = 32
          barSpacingBase = 3
        } else {
          // Larger screens
          totalBars = 48
          barSpacingBase = 4
        }

        const step = Math.floor(effectiveBufferLength / totalBars)
        const barSpacing = barSpacingBase * window.devicePixelRatio
        const barWidth = (width - (totalBars * barSpacing)) / totalBars

        for (let i = 0; i < totalBars; i++) {
          // Average bins for each bar
          let sum = 0
          for (let j = 0; j < step; j++) {
            sum += dataArray[i * step + j]
          }
          const average = sum / step

          // Normalize bar height - responsive minimum height
          const minBarHeight = (cssWidth < 200 ? 3 : 4) * window.devicePixelRatio
          const barHeight = Math.max(minBarHeight, (average / 255) * height * 0.9)

          // Create gradient for bars (Vibrant blue/indigo like Fig 1)
          const gradient = canvasCtx.createLinearGradient(0, (height - barHeight) / 2, 0, (height + barHeight) / 2)
          gradient.addColorStop(0, '#6366f1') // Indigo-500
          gradient.addColorStop(1, '#a855f7') // Purple-500

          canvasCtx.fillStyle = gradient

          // Draw rounded bars - responsive corner radius
          const radius = Math.min(barWidth / 2, (cssWidth < 200 ? 2 : 3) * window.devicePixelRatio)
          const x = i * (barWidth + barSpacing)
          const y = (height - barHeight) / 2

          canvasCtx.beginPath()
          if (canvasCtx.roundRect) {
              canvasCtx.roundRect(x, y, barWidth, barHeight, radius)
          } else {
              // Fallback for older browsers
              canvasCtx.rect(x, y, barWidth, barHeight)
          }
          canvasCtx.fill()
        }
      }

      draw()
      return () => {
        window.removeEventListener('resize', updateSize)
      }
    } else {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close()
      }
    }

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
      if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close()
      }
    }
  }, [isActive, stream])

  return (
    <canvas 
      ref={canvasRef} 
      className={`w-full h-full ${className || ''}`}
    />
  )
}
