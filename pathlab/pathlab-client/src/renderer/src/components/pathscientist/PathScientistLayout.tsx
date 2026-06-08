import React from 'react'
import { Link } from 'react-router-dom'

interface PathScientistLayoutProps {
  children: React.ReactNode
}

export default function PathScientistLayout({ children }: PathScientistLayoutProps) {
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="sticky top-0 z-40 border-b border-gray-200/70 bg-white/85 shadow-sm backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center px-4 sm:px-6 lg:px-8">
          <Link to="/pathscientist" className="flex items-center gap-3 transition-opacity hover:opacity-85">
            <img src="/images/pathlab-logo.png" alt="PathLab" className="h-9 w-auto" />
            <div className="hidden h-7 w-px bg-gray-200 sm:block" />
            <div className="flex items-center gap-2">
              <div className="leading-tight">
                <p className="text-sm font-bold tracking-tight text-gray-900">PathScientist</p>
              </div>
            </div>
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        {children}
      </main>
    </div>
  )
}
