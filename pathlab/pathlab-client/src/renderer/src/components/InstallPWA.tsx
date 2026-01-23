import React, { useState, useEffect } from 'react'
import { X, Share, PlusSquare, Download, MoreVertical } from 'lucide-react'
import { Button } from './ui/button'

export function InstallPWA() {
    const [supportsPWA, setSupportsPWA] = useState(false)
    const [promptInstall, setPromptInstall] = useState<any>(null)
    const [isIOS, setIsIOS] = useState(false)
    const [isAndroid, setIsAndroid] = useState(false)
    const [showPrompt, setShowPrompt] = useState(false)
    const [isHttps, setIsHttps] = useState(false)

    useEffect(() => {
        // Check if already in standalone mode (PWA installed)
        const isStandalone = window.matchMedia('(display-mode: standalone)').matches || (window.navigator as any).standalone
        if (isStandalone) return

        // Check if running over HTTPS or localhost (required for PWA install)
        const isSecure = window.location.protocol === 'https:' ||
                         window.location.hostname === 'localhost' ||
                         window.location.hostname === '127.0.0.1'
        setIsHttps(isSecure)

        // Detect platforms
        const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as any).MSStream
        const android = /Android/i.test(navigator.userAgent)
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth < 768
        setIsIOS(ios)
        setIsAndroid(android)

        const handler = (e: any) => {
            e.preventDefault()
            console.log('[PWA] beforeinstallprompt event captured')
            setSupportsPWA(true)
            setPromptInstall(e)
        }

        window.addEventListener('beforeinstallprompt', handler)

        // Also listen for app installed event
        window.addEventListener('appinstalled', () => {
            console.log('[PWA] App was installed')
            setShowPrompt(false)
            setPromptInstall(null)
        })

        // Log for debugging
        console.log('[PWA] Check:', { ios, android, isMobile, isStandalone, isSecure, isElectron: !!(window as any).electron })

        // Auto-show prompt after 3 seconds if not installed and on mobile
        // Only show if we're on HTTPS (PWA won't work on HTTP anyway)
        const timer = setTimeout(() => {
            if (!isStandalone && isMobile && !(window as any).electron && isSecure) {
                setShowPrompt(true)
            }
        }, 3000)

        return () => {
            window.removeEventListener('beforeinstallprompt', handler)
            clearTimeout(timer)
        }
    }, [])

    const onClick = async (evt: React.MouseEvent) => {
        evt.preventDefault()

        if (!promptInstall) {
            // If beforeinstallprompt wasn't captured, show manual instructions
            console.log('[PWA] No install prompt available, showing manual instructions')
            return
        }

        try {
            // Show the install prompt
            promptInstall.prompt()

            // Wait for the user choice
            const choiceResult = await promptInstall.userChoice
            if (choiceResult.outcome === 'accepted') {
                console.log('[PWA] User accepted the install')
            } else {
                console.log('[PWA] User dismissed the install')
            }

            // Clear the prompt - it can only be used once
            setPromptInstall(null)
            setShowPrompt(false)
        } catch (error) {
            console.error('[PWA] Install prompt error:', error)
        }
    }

    if (!showPrompt) return null

    // Determine which instructions to show
    const showInstallButton = supportsPWA && promptInstall
    const showAndroidManualInstructions = isAndroid && !supportsPWA
    const showIOSInstructions = isIOS

    return (
        <div className="fixed bottom-4 inset-x-4 z-[100] animate-in fade-in slide-in-from-bottom-5 duration-500">
            <div className="bg-white rounded-2xl shadow-2xl border border-gray-100 p-4 sm:p-5 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-primary-100 flex items-center justify-center flex-shrink-0">
                        <img src="/images/pwa-icon.png" alt="PathLab" className="w-10 h-10 object-contain" />
                    </div>
                    <div className="flex flex-col">
                        <h3 className="text-sm font-bold text-gray-900 leading-tight">Install PathLab</h3>
                        <p className="text-xs text-gray-500 mt-0.5">
                            {showIOSInstructions
                                ? 'Add to Home Screen for the best experience'
                                : 'Install our app local to your device'}
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {showIOSInstructions ? (
                        <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-50 rounded-lg border border-gray-100 text-[10px] font-medium text-gray-600">
                            Tap <Share className="w-3 h-3 inline" /> then <PlusSquare className="w-3 h-3 inline" />
                        </div>
                    ) : showAndroidManualInstructions ? (
                        <div className="flex items-center gap-2 px-3 py-2 bg-gray-50/80 backdrop-blur-sm rounded-lg border border-gray-200/60 text-xs font-medium text-gray-600 shadow-sm">
                            <span>Tap</span>
                            <div className="p-1 bg-white rounded border border-gray-200 shadow-sm">
                                <MoreVertical className="w-3.5 h-3.5 text-gray-800" />
                            </div>
                            <span className="flex items-center gap-1">
                                <span>to</span>
                                <span className="font-semibold text-gray-800">Install App</span>
                            </span>
                        </div>
                    ) : showInstallButton ? (
                        <Button size="sm" onClick={onClick} className="gap-2 h-9 px-4 text-xs font-semibold">
                            <Download className="w-3.5 h-3.5" />
                            Install
                        </Button>
                    ) : (
                        <div className="flex items-center gap-1.5 px-3 py-2 bg-gray-50 rounded-lg border border-gray-100 text-[10px] font-medium text-gray-600">
                            Use browser menu to install
                        </div>
                    )}
                    <button
                        onClick={() => setShowPrompt(false)}
                        className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </div>
    )
}
