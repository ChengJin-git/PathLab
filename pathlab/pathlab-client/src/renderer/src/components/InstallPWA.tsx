import { useState, useEffect } from 'react'
import { X, Share, PlusSquare, Download, MoreVertical, Smartphone } from 'lucide-react'
import { Button } from './ui/button'

export function InstallPWA() {
    const [supportsPWA, setSupportsPWA] = useState(false)
    const [promptInstall, setPromptInstall] = useState<any>(null)
    const [isIOS, setIsIOS] = useState(false)
    const [isAndroid, setIsAndroid] = useState(false)
    const [showPrompt, setShowPrompt] = useState(false)

    useEffect(() => {
        // Check if already in standalone mode (PWA installed)
        const isStandalone = window.matchMedia('(display-mode: standalone)').matches || (window.navigator as any).standalone
        if (isStandalone) return

        // Check if running over HTTPS or localhost (required for PWA install)
        const isSecure = window.location.protocol === 'https:' ||
                         window.location.hostname === 'localhost' ||
                         window.location.hostname === '127.0.0.1'

        // Detect platforms
        const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as any).MSStream
        const android = /Android/i.test(navigator.userAgent)
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || window.innerWidth < 768
        setIsIOS(ios)
        setIsAndroid(android)

        const handler = (e: any) => {
            e.preventDefault()
            setSupportsPWA(true)
            setPromptInstall(e)
        }

        window.addEventListener('beforeinstallprompt', handler)

        // Listen for app installed event
        window.addEventListener('appinstalled', () => {
            setShowPrompt(false)
            setPromptInstall(null)
        })

        // Auto-show prompt after 2 seconds if not installed and on mobile
        const timer = setTimeout(() => {
            if (!isStandalone && isMobile && !(window as any).electron && isSecure) {
                setShowPrompt(true)
            }
        }, 2000)

        return () => {
            window.removeEventListener('beforeinstallprompt', handler)
            clearTimeout(timer)
        }
    }, [])

    const onInstallClick = async () => {
        if (!promptInstall) return

        try {
            promptInstall.prompt()
            const choiceResult = await promptInstall.userChoice
            if (choiceResult.outcome === 'accepted') {
                setShowPrompt(false)
            }
            setPromptInstall(null)
        } catch (error) {
            // Install prompt error - silently ignore
        }
    }

    if (!showPrompt) return null

    // Android with beforeinstallprompt = one-click install
    const canOneClickInstall = supportsPWA && promptInstall
    // Android without beforeinstallprompt (e.g. Firefox on Android) = manual instructions
    const showAndroidManual = isAndroid && !supportsPWA

    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[99] md:hidden"
                onClick={() => setShowPrompt(false)}
            />

            {/* Bottom Sheet Modal - mobile only */}
            <div className="fixed bottom-0 inset-x-0 z-[100] md:hidden animate-in fade-in slide-in-from-bottom-8 duration-500">
                <div className="bg-white rounded-t-3xl shadow-2xl border-t border-gray-200 px-5 pt-4 pb-6 safe-bottom">
                    {/* Drag handle */}
                    <div className="flex justify-center mb-4">
                        <div className="w-10 h-1 rounded-full bg-gray-300" />
                    </div>

                    {/* Close button */}
                    <button
                        onClick={() => setShowPrompt(false)}
                        className="absolute top-4 right-4 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-colors"
                    >
                        <X className="w-5 h-5" />
                    </button>

                    {/* App icon + info */}
                    <div className="flex flex-col items-center text-center mb-5">
                        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 border border-gray-200 flex items-center justify-center mb-3 shadow-sm">
                            <img src="/images/pwa-icon.png" alt="PathLab" className="w-12 h-12 object-contain" />
                        </div>
                        <h3 className="text-lg font-bold text-gray-900">Install PathLab</h3>
                        <p className="text-sm text-gray-500 mt-1 max-w-[260px]">
                            {isIOS
                                ? 'Add PathLab to your Home Screen for the best experience'
                                : 'Install PathLab on your device for quick access'}
                        </p>
                    </div>

                    {/* iOS Instructions */}
                    {isIOS && (
                        <div className="space-y-3 mb-5">
                            <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-blue-600">1</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-gray-700">
                                    <span>Tap the</span>
                                    <Share className="w-4 h-4 text-blue-600" />
                                    <span className="font-semibold">Share</span>
                                    <span>button below</span>
                                </div>
                            </div>
                            <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-blue-600">2</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-gray-700">
                                    <span>Scroll and tap</span>
                                    <PlusSquare className="w-4 h-4 text-blue-600" />
                                    <span className="font-semibold">Add to Home Screen</span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Android manual instructions (Firefox etc.) */}
                    {showAndroidManual && (
                        <div className="space-y-3 mb-5">
                            <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-blue-600">1</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-gray-700">
                                    <span>Tap the</span>
                                    <MoreVertical className="w-4 h-4 text-gray-800" />
                                    <span className="font-semibold">menu button</span>
                                </div>
                            </div>
                            <div className="flex items-center gap-3 p-3 bg-gray-50 rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-blue-600">2</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-gray-700">
                                    <span>Tap</span>
                                    <Download className="w-4 h-4 text-blue-600" />
                                    <span className="font-semibold">Install App</span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Android one-click install button (Chrome) */}
                    {canOneClickInstall && (
                        <Button
                            onClick={onInstallClick}
                            className="w-full h-12 bg-blue-600 hover:bg-blue-700 text-white font-semibold text-base rounded-xl shadow-lg shadow-blue-200 flex items-center justify-center gap-2 transition-all"
                        >
                            <Download className="w-5 h-5" />
                            Install Now
                        </Button>
                    )}

                    {/* Fallback for non-iOS/non-Android mobile or generic */}
                    {!isIOS && !isAndroid && !canOneClickInstall && (
                        <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-xl text-sm text-gray-600">
                            <Smartphone className="w-4 h-4 text-gray-500" />
                            <span>Use your browser menu to install this app</span>
                        </div>
                    )}

                    {/* Dismiss link */}
                    <button
                        onClick={() => setShowPrompt(false)}
                        className="w-full mt-3 py-2 text-sm text-gray-400 hover:text-gray-600 transition-colors text-center"
                    >
                        Not now
                    </button>
                </div>
            </div>
        </>
    )
}
