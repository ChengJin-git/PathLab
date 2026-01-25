/**
 * PathLab Login Page
 *
 * Landing page with username/password login.
 * Registration is only available through admin in Settings.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { initializeApiConfig, getApiBase } from '../config'
import { Microscope, Brain, Shield, Zap, LogIn, Loader2, User, Lock } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, isLoading, error, isLoggedIn } = useAuth()

  // Form state
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [formError, setFormError] = React.useState<string | null>(null)

  // Auto-login in test/development environment
  React.useEffect(() => {
    const attemptAutoLogin = async () => {
      // Wait for API config to be initialized
      await initializeApiConfig()
      console.log('[Login] API config initialized, API_BASE:', getApiBase())
      
      const isDev = import.meta.env.DEV || import.meta.env.MODE === 'development'
      const autoLoginEnabled = import.meta.env.VITE_AUTO_LOGIN === 'true' || 
                              localStorage.getItem('auto_login') === 'true' ||
                              (isDev && localStorage.getItem('auto_login') !== 'false')
      
      if (autoLoginEnabled && !isLoggedIn && !isLoading) {
        const testUsername = import.meta.env.VITE_TEST_USERNAME || 'admin'
        const testPassword = import.meta.env.VITE_TEST_PASSWORD || 'Smartlab2022'
        
        console.log('[Login] Auto-login enabled, attempting login...')
        try {
          const success = await login(testUsername, testPassword)
          if (success) {
            navigate('/dashboard')
          }
        } catch (err) {
          console.warn('[Login] Auto-login failed:', err)
          // Retry once after a short delay
          setTimeout(async () => {
            try {
              const retrySuccess = await login(testUsername, testPassword)
              if (retrySuccess) {
                navigate('/dashboard')
              }
            } catch (retryErr) {
              console.warn('[Login] Auto-login retry also failed:', retryErr)
            }
          }, 2000)
        }
      }
    }
    
    attemptAutoLogin()
  }, [isLoggedIn, isLoading, login, navigate])

  // If already logged in, redirect to dashboard
  React.useEffect(() => {
    if (isLoggedIn) {
      navigate('/dashboard')
    }
  }, [isLoggedIn, navigate])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    if (!username || !password) {
      setFormError('Please enter username and password')
      return
    }

    const success = await login(username, password)
    if (success) {
      navigate('/dashboard')
    }
  }

  const features = [
    {
      icon: Microscope,
      title: 'WSI Visualization',
      description: 'View and navigate multi-gigapixel whole slide images with smooth pan and zoom',
    },
    {
      icon: Brain,
      title: 'AI-Powered Analysis',
      description: 'Train and deploy deep learning models for pathology classification',
    },
    {
      icon: Shield,
      title: 'Privacy First',
      description: 'Your data never leaves your machine - models come to the data',
    },
    {
      icon: Zap,
      title: 'Smart Assistant',
      description: 'Describe your research in natural language, let AI set up the task',
    },
  ]

  return (
    <div className="h-screen bg-gradient-to-br from-slate-100 via-gray-100 to-slate-200 flex flex-col overflow-hidden">
      {/* Header */}
      <header className="px-8 py-4 flex items-center justify-between">
        <img
          src="/images/pathlab-logo.png"
          alt="PathLab"
          className="h-12 w-auto"
        />
      </header>

      <main className="flex-1 flex flex-col justify-center px-6 py-4 relative">
        <div className="max-w-7xl w-full mx-auto">
          {/* Hero Section - Compact */}
          <div className="mb-6 lg:mb-8 text-center lg:text-left">
            <h2 className="text-3xl lg:text-4xl font-black text-slate-800 leading-[1.1] mb-2">
              Digital Pathology{' '}
              <span className="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
                Powered by AI
              </span>
            </h2>
            <p className="text-slate-500 text-sm font-medium max-w-2xl">
              An AI agentic platform for pathology research. Train, analyze, and gain insights while keeping your data private.
            </p>
          </div>

          <div className="grid lg:grid-cols-2 gap-6 items-stretch">
            {/* Left: Login Box */}
            <div className="bg-white/90 backdrop-blur-md rounded-[2rem] border border-slate-200 p-8 shadow-2xl flex flex-col justify-center relative overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/5 rounded-full -mr-16 -mt-16 blur-2xl" />
              <form onSubmit={handleLogin} className="space-y-5 relative z-10">
                <div>
                  <h3 className="text-2xl font-black text-slate-800 tracking-tight">
                    Welcome Back
                  </h3>
                  <p className="text-slate-400 text-sm mt-1">Sign in to continue</p>
                </div>

                <div className="space-y-4">
                  <div className="space-y-1">
                    <label className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 ml-1">Username</label>
                    <div className="relative group">
                      <User className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                      <Input
                        id="username"
                        type="text"
                        placeholder="username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="pl-12 h-11 bg-slate-50/50 border-slate-200 focus:bg-white focus:ring-4 focus:ring-blue-100 rounded-xl transition-all text-sm"
                        disabled={isLoading}
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 ml-1">Password</label>
                    <div className="relative group">
                      <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-500 transition-colors" />
                      <Input
                        id="password"
                        type="password"
                        placeholder="••••••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        className="pl-12 h-11 bg-slate-50/50 border-slate-200 focus:bg-white focus:ring-4 focus:ring-blue-100 rounded-xl transition-all text-sm"
                        disabled={isLoading}
                      />
                    </div>
                  </div>

                </div>

                {/* Error Message */}
                {(error || formError) && (
                  <div className="p-3 bg-rose-50 border border-rose-100 rounded-xl text-rose-600 text-[13px] font-semibold flex items-center gap-2">
                    <div className="w-1 h-4 rounded-full bg-rose-600" />
                    {formError || error}
                  </div>
                )}

                <div className="space-y-3">
                  <Button
                    type="submit"
                    disabled={isLoading}
                    className="w-full h-11 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-200 hover:shadow-blue-300 hover:-translate-y-0.5 transition-all flex items-center justify-center gap-2"
                  >
                    {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <LogIn className="w-5 h-5" />}
                    Sign In
                  </Button>

                  <p className="text-center text-xs text-slate-400">
                    Contact your administrator for account access
                  </p>
                </div>
              </form>
            </div>

            {/* Right: Feature Cards */}
            <div className="grid grid-cols-2 gap-4">
              {features.map((feature) => {
                const Icon = feature.icon
                return (
                  <div
                    key={feature.title}
                    className="group bg-white/70 backdrop-blur-sm rounded-[2rem] border border-slate-200 p-6 flex flex-col justify-center hover:border-blue-200 hover:shadow-xl hover:shadow-blue-500/5 transition-all duration-300"
                  >
                    <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center mb-3 text-blue-600 group-hover:scale-110 group-hover:bg-blue-600 group-hover:text-white transition-all duration-300">
                      <Icon className="w-5 h-5" />
                    </div>
                    <h3 className="text-base font-bold text-slate-800 mb-1 group-hover:text-blue-600 transition-colors">{feature.title}</h3>
                    <p className="text-[12px] text-slate-500 leading-relaxed font-medium line-clamp-3">{feature.description}</p>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="py-4 text-center text-slate-400 text-[11px] font-medium border-t border-slate-100 bg-white/50">
        <p>© 2026 SmartLab · AI for digital pathology</p>
      </footer>
    </div>
  )
}
