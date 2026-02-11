import { useState, useEffect, useCallback } from 'react'
import { X, Share, PlusSquare, Download, MoreVertical, Smartphone, ExternalLink, Copy, Check } from 'lucide-react'
import { Button } from './ui/button'

// ---- Cooldown constants ----
const PWA_DISMISS_KEY = 'pwa-install-dismissed'
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

// ---- Browser environment detection helpers ----

/** In-app browsers that cannot install PWA at all */
function detectInAppBrowser(ua: string): string | null {
    // Order matters: WeChat check must come before QQ (WeChat UA also contains QQ)
    if (/MicroMessenger/i.test(ua)) return 'wechat'
    if (/QQ\//i.test(ua)) return 'qq'
    if (/Weibo/i.test(ua)) return 'weibo'
    if (/AlipayClient/i.test(ua)) return 'alipay'
    if (/DingTalk/i.test(ua)) return 'dingtalk'
    if (/BytedanceWebview|TikTok|Douyin/i.test(ua)) return 'douyin'
    if (/Line\//i.test(ua)) return 'line'
    if (/FBAN|FBAV|FB_IAB/i.test(ua)) return 'facebook'
    if (/Instagram/i.test(ua)) return 'instagram'
    if (/Twitter|TwitterAndroid/i.test(ua)) return 'twitter'
    return null
}

/**
 * Whitelist: browsers known to support real PWA installation (not just shortcuts).
 * Returns true only for Chrome, Edge, Samsung Internet, and Opera on Android.
 * All other Android browsers (Xiaomi, Huawei, OPPO, Vivo, UC, QQ Browser, etc.)
 * will be treated as unsupported and shown a "use Chrome" guide.
 */
function isRealPWABrowser(ua: string): boolean {
    // Edge (contains "Edg/" in UA, must check before Chrome since Edge UA also contains "Chrome")
    if (/Edg\//i.test(ua)) return true
    // Samsung Internet
    if (/SamsungBrowser/i.test(ua)) return true
    // Opera
    if (/OPR\//i.test(ua)) return true
    // Chrome (must be last: many Chromium-based browsers include "Chrome" in UA)
    // Exclude known non-Chrome Chromium browsers by checking none of the above matched
    // and no known domestic browser identifiers are present
    if (/Chrome\/[0-9]/i.test(ua)) {
        // Exclude domestic Chromium-based browsers that include "Chrome" in UA
        if (/MiuiBrowser|HuaweiBrowser|HeyTapBrowser|VivoBrowser|UCBrowser|MQQBrowser|Quark|Sogou|Baidu|360SE|360EE|Lenovo|Maxthon|TheWorld|LBBROWSER|BIDUBrowser|baiduboxapp|QihooBrowser|LieBao|MicroMessenger/i.test(ua)) {
            return false
        }
        return true
    }
    return false
}


export function InstallPWA() {
    const [supportsPWA, setSupportsPWA] = useState(false)
    const [promptInstall, setPromptInstall] = useState<any>(null)
    const [isIOS, setIsIOS] = useState(false)
    const [isAndroid, setIsAndroid] = useState(false)
    const [showPrompt, setShowPrompt] = useState(false)
    const [inAppBrowser, setInAppBrowser] = useState<string | null>(null)
    const [unsupportedBrowser, setUnsupportedBrowser] = useState(false)
    const [copied, setCopied] = useState(false)

    useEffect(() => {
        // Check if already in standalone mode (PWA installed)
        const isStandalone = window.matchMedia('(display-mode: standalone)').matches || (window.navigator as any).standalone
        if (isStandalone) return

        // Check if running over HTTPS or localhost (required for PWA install)
        const isSecure = window.location.protocol === 'https:' ||
                         window.location.hostname === 'localhost' ||
                         window.location.hostname === '127.0.0.1'

        const ua = navigator.userAgent

        // Detect platforms
        const ios = /iPad|iPhone|iPod/.test(ua) && !(window as any).MSStream
        const android = /Android/i.test(ua)
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua) || window.innerWidth < 768
        setIsIOS(ios)
        setIsAndroid(android)

        // Detect special browser environments
        const inApp = detectInAppBrowser(ua)
        setInAppBrowser(inApp)

        // On Android, check if the browser truly supports PWA (whitelist approach)
        if (android && !inApp && !isRealPWABrowser(ua)) {
            setUnsupportedBrowser(true)
        }

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

        // Check if user dismissed recently (cooldown)
        const dismissedAt = localStorage.getItem(PWA_DISMISS_KEY)
        if (dismissedAt) {
            const dismissedTime = parseInt(dismissedAt, 10)
            if (Date.now() - dismissedTime < COOLDOWN_MS) {
                return // Don't show prompt during cooldown period
            }
        }

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

    /** Dismiss with cooldown – used by "Not now" / "暂不安装" buttons */
    const handleDismiss = useCallback(() => {
        try {
            localStorage.setItem(PWA_DISMISS_KEY, Date.now().toString())
        } catch {
            // localStorage may be unavailable in some contexts; ignore
        }
        setShowPrompt(false)
    }, [])

    const handleCopyLink = useCallback(() => {
        const url = window.location.href
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 2000)
            })
        } else {
            const textArea = document.createElement('textarea')
            textArea.value = url
            textArea.style.position = 'fixed'
            textArea.style.opacity = '0'
            document.body.appendChild(textArea)
            textArea.select()
            document.execCommand('copy')
            document.body.removeChild(textArea)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        }
    }, [])

    if (!showPrompt) return null

    // ---- Render: In-app browser overlay (WeChat, QQ, etc.) ----
    if (inAppBrowser) {
        const inAppName: Record<string, string> = {
            wechat: '微信', qq: 'QQ', weibo: '微博', alipay: '支付宝',
            dingtalk: '钉钉', douyin: '抖音', line: 'LINE',
            facebook: 'Facebook', instagram: 'Instagram', twitter: 'X/Twitter',
        }
        const browserName = inAppName[inAppBrowser] || inAppBrowser

        return (
            <>
                {/* Full-screen dark overlay */}
                <div
                    className="fixed inset-0 bg-black/80 z-[200] md:hidden flex flex-col"
                    onClick={() => setShowPrompt(false)}
                >
                    {/* Arrow pointing to top-right "..." button */}
                    <div className="flex justify-end pt-2 pr-4">
                        <div className="flex flex-col items-center animate-bounce">
                            <svg width="48" height="48" viewBox="0 0 48 48" fill="none" className="text-white">
                                <path d="M24 40V12" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                                <path d="M12 24L24 12L36 24" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </div>
                    </div>

                    {/* Guide content */}
                    <div className="flex-1 flex flex-col items-center justify-center px-8" onClick={e => e.stopPropagation()}>
                        <div className="w-20 h-20 rounded-2xl bg-white/10 backdrop-blur flex items-center justify-center mb-6">
                            <img src="/images/pwa-icon.png" alt="PathLab" className="w-14 h-14 object-contain" />
                        </div>

                        <h2 className="text-xl font-bold text-white mb-3 text-center">
                            PathLab 支持安装为应用
                        </h2>
                        <p className="text-white/70 text-sm text-center mb-6 max-w-[280px]">
                            {browserName} 内置浏览器不支持安装，请点击右上角菜单，选择在浏览器中打开
                        </p>

                        {/* Step-by-step guide */}
                        <div className="w-full max-w-[300px] space-y-3 mb-8">
                            <div className="flex items-center gap-3 p-3 bg-white/10 backdrop-blur rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-white">1</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-white">
                                    <span>点击右上角</span>
                                    <span className="font-bold text-lg tracking-wider">···</span>
                                    <span>按钮</span>
                                </div>
                            </div>
                            <div className="flex items-center gap-3 p-3 bg-white/10 backdrop-blur rounded-xl">
                                <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center flex-shrink-0">
                                    <span className="text-sm font-bold text-white">2</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-sm text-white">
                                    <span>选择</span>
                                    <ExternalLink className="w-4 h-4 text-blue-300" />
                                    <span className="font-semibold text-blue-300">
                                        {isIOS ? '在 Safari 中打开' : '在浏览器中打开'}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Copy link as fallback */}
                        <button
                            onClick={handleCopyLink}
                            className="flex items-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/20 rounded-xl text-white/80 text-sm transition-colors"
                        >
                            {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                            {copied ? '已复制链接' : '复制链接到剪贴板'}
                        </button>
                    </div>

                    {/* Dismiss */}
                    <div className="pb-8 flex justify-center">
                        <button
                            onClick={handleDismiss}
                            className="text-white/40 text-sm hover:text-white/60 transition-colors"
                        >
                            暂不安装
                        </button>
                    </div>
                </div>
            </>
        )
    }

    // ---- Render: Unsupported browser notice (non-Chrome/Edge/Samsung on Android) ----
    // Simple informational notice: PathLab supports installation, but this browser doesn't.
    // User dismisses and continues using the web version.
    if (unsupportedBrowser) {
        return (
            <>
                {/* Backdrop */}
                <div
                    className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[99] md:hidden"
                    onClick={handleDismiss}
                />

                {/* Bottom Sheet */}
                <div className="fixed bottom-0 inset-x-0 z-[100] md:hidden animate-in fade-in slide-in-from-bottom-8 duration-500">
                    <div className="bg-white rounded-t-3xl shadow-2xl border-t border-gray-200 px-5 pt-4 pb-6 safe-bottom">
                        {/* Drag handle */}
                        <div className="flex justify-center mb-4">
                            <div className="w-10 h-1 rounded-full bg-gray-300" />
                        </div>

                        {/* Close button */}
                        <button
                            onClick={handleDismiss}
                            className="absolute top-4 right-4 p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-full transition-colors"
                        >
                            <X className="w-5 h-5" />
                        </button>

                        {/* App icon + info */}
                        <div className="flex flex-col items-center text-center mb-5">
                            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 border border-gray-200 flex items-center justify-center mb-3 shadow-sm">
                                <img src="/images/pwa-icon.png" alt="PathLab" className="w-12 h-12 object-contain" />
                            </div>
                            <h3 className="text-lg font-bold text-gray-900">PathLab 支持安装为应用</h3>
                            <p className="text-sm text-gray-500 mt-2 max-w-[280px] leading-relaxed">
                                当前浏览器暂不支持此功能，你可以继续使用网页版，体验完全一致。
                            </p>
                            <p className="text-xs text-gray-400 mt-1.5 max-w-[280px] leading-relaxed">
                                或者换用 <a href="https://sj.qq.com/appdetail/com.android.chrome/" target="_blank" rel="noopener noreferrer" className="text-blue-500 underline">Chrome</a>、<a href="https://sj.qq.com/appdetail/com.tencent.pcgame.msedgepc/" target="_blank" rel="noopener noreferrer" className="text-blue-500 underline">Edge</a> 等浏览器安装
                            </p>
                        </div>

                        <Button
                            onClick={handleDismiss}
                            className="w-full h-12 bg-gray-900 hover:bg-gray-800 text-white font-semibold text-base rounded-xl transition-all"
                        >
                            知道了，继续使用网页版
                        </Button>
                    </div>
                </div>
            </>
        )
    }

    // ---- Render: Normal PWA install flow (Chrome, Safari, Edge, etc.) ----
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
                        <h3 className="text-lg font-bold text-gray-900">PathLab 支持安装为应用</h3>
                        <p className="text-sm text-gray-500 mt-1 max-w-[260px]">
                            {isIOS
                                ? '将 PathLab 添加到主屏幕，获得最佳体验'
                                : '将 PathLab 安装到设备，方便快速访问'}
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
                        onClick={handleDismiss}
                        className="w-full mt-3 py-2 text-sm text-gray-400 hover:text-gray-600 transition-colors text-center"
                    >
                        Not now
                    </button>
                </div>
            </div>
        </>
    )
}
