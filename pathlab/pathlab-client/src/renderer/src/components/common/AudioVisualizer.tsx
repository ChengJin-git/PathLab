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
        const totalBars = 48 // Slightly fewer bars for a cleaner look
        const step = Math.floor(effectiveBufferLength / totalBars)
        const barSpacing = 4 * window.devicePixelRatio
        const barWidth = (width - (totalBars * barSpacing)) / totalBars
        
        for (let i = 0; i < totalBars; i++) {
          // Average bins for each bar
          let sum = 0
          for (let j = 0; j < step; j++) {
            sum += dataArray[i * step + j]
          }
          const average = sum / step
          
          // Normalize bar height (Reference Fig 1 shows bars taking significant height)
          const barHeight = Math.max(4 * window.devicePixelRatio, (average / 255) * height * 0.9)
          
          // Create gradient for bars (Vibrant blue/indigo like Fig 1)
          const gradient = canvasCtx.createLinearGradient(0, (height - barHeight) / 2, 0, (height + barHeight) / 2)
          gradient.addColorStop(0, '#6366f1') // Indigo-500
          gradient.addColorStop(1, '#a855f7') // Purple-500
          
          canvasCtx.fillStyle = gradient
          
          // Draw rounded bars similar to Figure 1
          const radius = barWidth / 2
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
