import React, { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats, transcribeAudio } from '../api'
import { Microscope, CheckCircle, Settings as SettingsIcon, BarChart3, Bot, Rocket, ClipboardList, FolderOpen, Settings, TrendingUp, FileText, Upload, LayoutGrid, Mic, MicOff, Loader2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Badge } from '../components/ui/badge'
import { AudioVisualizer } from '../components/common/AudioVisualizer'

interface Stats {
    wsi_count: number
    task_count: number
    completed_count: number
    results_count: number
    labels: Record<string, number>
}

interface QuickAction {
    title: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    path: string
    color: string
}

export default function DashboardPage() {
    const navigate = useNavigate()
    const [stats, setStats] = useState<Stats | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [taskInput, setTaskInput] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)

    const [toastMessage, setToastMessage] = useState<{ type: 'error' | 'success' | 'info'; message: string } | null>(null)

    useEffect(() => {
        loadStats()
    }, [])

    const loadStats = async () => {
        try {
            const data = await fetchStats() as unknown as Stats
            setStats(data)
            setError(null)
        } catch (err) {
            setError(String(err))
        } finally {
            setLoading(false)
        }
    }

    const handleTaskSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!taskInput.trim()) return

        setIsSubmitting(true)
        try {
            // Navigate to AI Chat with the task description
            navigate('/ai-chat', { state: { initialMessage: taskInput } })

            // 清空输入框
            setTaskInput('')
        } catch (err) {
            console.error('Failed to submit task:', err)
            window.alert('Failed to submit task: ' + String(err))
        } finally {
            setIsSubmitting(false)
        }
    }

    // Toast helper function
    const showToast = (type: 'error' | 'success' | 'info', message: string) => {
        setToastMessage({ type, message })
        setTimeout(() => setToastMessage(null), 5000)
    }

    const toggleRecording = () => {
        navigate('/ai-chat', { state: { autoStartRecording: true, fromDashboard: true } })
    }

    const quickActions: QuickAction[] = [
        {
            title: 'Register Files',
            description: 'Register local files',
            icon: Upload,
            path: '/register',
            color: 'text-cyan-600',
        },
        {
            title: 'File Browser',
            description: 'Manage and view registered files',
            icon: FolderOpen,
            path: '/wsi-list',
            color: 'text-indigo-600',
        },
        {
            title: 'Task Browser',
            description: 'View past analysis tasks and results',
            icon: ClipboardList,
            path: '/task-list',
            color: 'text-sky-600',
        },
        {
            title: 'Advanced Tools',
            description: 'Custom pipelines & Reports',
            icon: LayoutGrid,
            path: '/tools',
            color: 'text-slate-600',
        },
    ]

    const greeting = () => {
        const hour = new Date().getHours()
        if (hour < 12) return 'Good morning'
        if (hour < 18) return 'Good afternoon'
        return 'Good evening'
    }

    return (
        <div className="flex-1 flex flex-col justify-center py-2 sm:py-4 space-y-6 sm:space-y-10 w-full max-w-[1600px] mx-auto px-4 sm:px-10">
            {/* Header */}
            <div className="space-y-1 text-center">
                <h1 className="text-xl sm:text-4xl font-bold tracking-tight text-gray-900">{greeting()}, Researcher</h1>
                <p className="text-sm sm:text-lg text-gray-600">
                    Ready to discover precise pathology insights today?
                </p>
            </div>

            {/* Main Focus: AI Assistant */}
            <Card className="border-primary-100 shadow-md bg-gradient-to-br from-white to-primary-50/30 overflow-hidden">
                <CardContent className="p-4 sm:p-8">
                    <div className="flex flex-col items-center justify-center space-y-4 sm:space-y-6 text-center">
                        {/* Smaller icon */}
                        <div className="w-12 h-12 sm:w-20 sm:h-20 bg-primary-100 rounded-2xl flex items-center justify-center mb-2 sm:mb-4 shadow-lg shadow-primary-200">
                            <Bot className="w-6 h-6 sm:w-10 sm:h-10 text-primary-600" />
                        </div>
                        <div className="space-y-1 sm:space-y-3 max-w-3xl">
                            <h2 className="text-lg sm:text-3xl font-semibold text-gray-900 leading-tight">What would you like to research?</h2>
                            <p className="text-gray-500 text-xs sm:text-lg px-4 sm:px-0">I can help you classify tumors, segment cells, or analyze WSI patterns.</p>
                        </div>

                        <form onSubmit={handleTaskSubmit} className="w-full max-w-5xl">
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-4 sm:pl-8 flex items-center pointer-events-none z-10">
                                    <Bot className="h-5 w-5 sm:h-6 sm:w-6 text-gray-400 group-focus-within:text-primary-500 transition-colors" />
                                </div>
                                <Input
                                    type="text"
                                    className="pl-12 pr-14 sm:pl-16 sm:pr-[280px] h-12 sm:h-20 text-sm sm:text-xl rounded-xl sm:rounded-2xl border-gray-200 shadow-sm focus:border-primary-400 focus:ring-0 py-2 sm:py-4 transition-all w-full bg-white"
                                    placeholder="e.g. Detect tumor regions..."
                                    value={taskInput}
                                    onChange={(e) => setTaskInput(e.target.value)}
                                    onFocus={() => navigate('/ai-chat', { state: { fromDashboard: true } })}
                                    disabled={isSubmitting}
                                />
                                
                                <div className="absolute right-2 sm:right-3 top-2 bottom-2 sm:top-3 sm:bottom-3 flex items-center gap-2 sm:gap-3">
                                     <button
                                        type="button"
                                        onClick={toggleRecording}
                                        disabled={isSubmitting}
                                        className="p-1.5 sm:p-2.5 h-full aspect-square flex items-center justify-center rounded-lg sm:rounded-xl transition-all shadow-sm bg-gray-100 text-gray-500 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                                        title="Voice input"
                                     >
                                        <Mic className="w-4 h-4 sm:w-5 sm:h-5" />
                                     </button>
                                     <Button
                                        type="submit"
                                        disabled={!taskInput.trim() || isSubmitting}
                                        size="lg"
                                        className="hidden sm:flex h-full rounded-xl px-5 lg:px-8 text-base sm:text-lg font-medium shadow-sm hover:shadow-md transition-all active:scale-95"
                                     >
                                        {isSubmitting ? 'Thinking...' : 'Start Research'}
                                     </Button>
                                </div>
                            </div>
                            <div className="mt-3 sm:hidden">
                                <Button
                                    type="submit"
                                    disabled={!taskInput.trim() || isSubmitting}
                                    size="lg"
                                    className="w-full h-12 rounded-xl text-base font-medium shadow-sm"
                                >
                                    {isSubmitting ? 'Thinking...' : 'Start Research'}
                                </Button>
                            </div>
                        </form>
                    </div>
                </CardContent>
            </Card>

            {/* Quick Actions Grid */}
            <div className="space-y-4 sm:space-y-6 pb-2">
                <div className="text-center">
                    <h3 className="text-base sm:text-xl font-semibold text-gray-900">Quick Actions</h3>
                </div>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
                    {quickActions.map((action, index) => {
                        const Icon = action.icon
                        return (
                            <Card
                                key={index}
                                className="group cursor-pointer hover:border-primary-200 hover:shadow-lg transition-all active:scale-95 bg-white/50 hover:bg-white"
                                onClick={() => navigate(action.path)}
                            >
                                <CardContent className="p-3 sm:p-6 flex flex-col items-center text-center space-y-2 sm:space-y-4">
                                    <div className={`p-2 sm:p-4 rounded-3xl bg-gray-50 group-hover:bg-primary-50 transition-colors border border-gray-100 group-hover:border-primary-100`}>
                                        <Icon className={`w-6 h-6 sm:w-10 sm:h-10 ${action.color}`} />
                                    </div>
                                    <div>
                                        <h4 className="font-semibold text-sm sm:text-lg text-gray-900">{action.title}</h4>
                                        <p className="text-[10px] sm:text-sm text-gray-500 mt-0.5 sm:mt-1 leading-tight">{action.description}</p>
                                    </div>
                                </CardContent>
                            </Card>
                        )
                    })}
                </div>
            </div>

            {/* Toast notification */}
            {toastMessage && (
                <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 max-w-sm sm:max-w-md ${
                    toastMessage.type === 'error' ? 'bg-red-500 text-white' :
                    toastMessage.type === 'success' ? 'bg-green-500 text-white' : 'bg-blue-500 text-white'
                }`}>
                    <span className="text-sm sm:text-base">{toastMessage.message}</span>
                    <button
                        onClick={() => setToastMessage(null)}
                        className="ml-2 hover:opacity-80 text-lg"
                    >
                        ×
                    </button>
                </div>
            )}
        </div>
    )
}
