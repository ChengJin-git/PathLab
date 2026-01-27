import React, { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats, fetchRecentActivity, invalidateRecentActivityCache, RecentUpload, RecentTask } from '../api'
import { Microscope, CheckCircle, Settings as SettingsIcon, BarChart3, Bot, Rocket, ClipboardList, FolderOpen, Settings, TrendingUp, FileText, Upload, LayoutGrid, Mic, MicOff, Loader2, Bell, ArrowRight, X, RefreshCw, Brain, Database, LineChart, ChevronRight, Sparkles } from 'lucide-react'
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

    // Recent activity state
    const [recentUploads, setRecentUploads] = useState<RecentUpload[]>([])
    const [recentTasks, setRecentTasks] = useState<RecentTask[]>([])
    const [activityLoading, setActivityLoading] = useState(true)

    // Dismissed items state (persisted in localStorage)
    const [dismissedUploads, setDismissedUploads] = useState<string[]>([])
    const [dismissedTasks, setDismissedTasks] = useState<string[]>([])

    // Load dismissed items from localStorage on mount
    useEffect(() => {
        try {
            const storedDismissedUploads = localStorage.getItem('dashboard_dismissed_uploads')
            const storedDismissedTasks = localStorage.getItem('dashboard_dismissed_tasks')
            if (storedDismissedUploads) {
                setDismissedUploads(JSON.parse(storedDismissedUploads))
            }
            if (storedDismissedTasks) {
                setDismissedTasks(JSON.parse(storedDismissedTasks))
            }
        } catch (e) {
            console.error('Failed to load dismissed items from localStorage:', e)
        }
    }, [])

    // Dismiss handlers
    const dismissUpload = (wsiId: string, e: React.MouseEvent) => {
        e.stopPropagation() // Prevent navigation
        const newDismissed = [...dismissedUploads, wsiId]
        setDismissedUploads(newDismissed)
        localStorage.setItem('dashboard_dismissed_uploads', JSON.stringify(newDismissed))
    }

    const dismissTask = (taskId: string, e: React.MouseEvent) => {
        e.stopPropagation() // Prevent navigation
        const newDismissed = [...dismissedTasks, taskId]
        setDismissedTasks(newDismissed)
        localStorage.setItem('dashboard_dismissed_tasks', JSON.stringify(newDismissed))
    }

    // Filter out dismissed items
    const visibleUploads = recentUploads.filter(u => !dismissedUploads.includes(u.wsi_id))
    const visibleTasks = recentTasks.filter(t => !dismissedTasks.includes(t.task_id))

    useEffect(() => {
        loadStats()
        loadRecentActivity()
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

    const loadRecentActivity = async (forceRefresh: boolean = false) => {
        try {
            if (forceRefresh) {
                setActivityLoading(true)
            }
            const data = await fetchRecentActivity(5, 5, forceRefresh)
            setRecentUploads(data.recent_uploads)
            setRecentTasks(data.recent_tasks)
        } catch (err) {
            console.error('Failed to load recent activity:', err)
        } finally {
            setActivityLoading(false)
        }
    }

    // Refresh recent activity (force refresh from server)
    const refreshRecentActivity = () => {
        invalidateRecentActivityCache()
        loadRecentActivity(true)
    }

    // Format relative time
    const formatRelativeTime = (dateStr: string | null) => {
        if (!dateStr) return ''
        const date = new Date(dateStr)
        const now = new Date()
        const diffMs = now.getTime() - date.getTime()
        const diffMins = Math.floor(diffMs / (1000 * 60))
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

        if (diffMins < 1) return 'Just now'
        if (diffMins < 60) return `${diffMins} minutes ago`
        if (diffHours < 24) return `${diffHours} hours ago`
        if (diffDays < 7) return `${diffDays} days ago`
        return date.toLocaleDateString()
    }

    // Get status badge color
    const getStatusColor = (status: string) => {
        switch (status) {
            case 'completed': return 'bg-emerald-50 text-emerald-700 border-emerald-100'
            case 'running': return 'bg-blue-50 text-blue-700 border-blue-100'
            case 'pending': return 'bg-amber-50 text-amber-700 border-amber-100'
            case 'failed': return 'bg-rose-50 text-rose-700 border-rose-100'
            default: return 'bg-slate-50 text-slate-700 border-slate-100'
        }
    }

    const handleTaskSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!taskInput.trim()) return

        setIsSubmitting(true)
        try {
            // Navigate to AI Chat with the task description
            navigate('/ai-chat', { state: { initialMessage: taskInput } })

            // Clear input
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

    const workflowModules = [
        {
            title: 'Data Repository',
            description: 'Manage WSI slides',
            icon: Database,
            mainAction: { label: 'Browse', path: '/wsi-list' },
            subAction: { label: 'Register', path: '/register' },
            color: 'text-blue-600',
            bg: 'bg-blue-50',
            border: 'border-blue-100',
            ring: 'focus-within:ring-blue-500',
        },
        {
            title: 'Analysis Lab',
            description: 'Run & monitor tasks',
            icon: Brain,
            mainAction: { label: 'Tasks', path: '/task-list' },
            subAction: { label: 'New Run', path: '/ai-chat' },
            color: 'text-violet-600',
            bg: 'bg-violet-50',
            border: 'border-violet-100',
            ring: 'focus-within:ring-violet-500',
        },
        {
            title: 'Insights & Reports',
            description: 'Visualize findings',
            icon: LineChart,
            mainAction: { label: 'Reports', path: '/tools' }, // Placeholder for reports
            subAction: null,
            color: 'text-emerald-600',
            bg: 'bg-emerald-50',
            border: 'border-emerald-100',
            ring: 'focus-within:ring-emerald-500',
        },
    ]

    const greeting = () => {
        const hour = new Date().getHours()
        if (hour < 12) return 'Good morning'
        if (hour < 18) return 'Good afternoon'
        return 'Good evening'
    }

    return (
        <div className="flex-1 flex flex-col w-full max-w-[1600px] mx-auto px-4 sm:px-8 py-6 space-y-8">
            {/* Header Section */}
            <div className="flex flex-col md:flex-row items-start md:items-end justify-between gap-4">
                <div className="space-y-1">
                    <h1 className="text-3xl font-bold tracking-tight text-gray-900">{greeting()}, Researcher</h1>
                    <p className="text-gray-500 text-lg">
                        What would you like to discover today?
                    </p>
                </div>
                {/* Optional: System Status or simple date could go here */}
            </div>

            {/* AI Command Center - Hero */}
            <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-3xl opacity-50 transform -skew-y-1 scale-y-110" />
                <Card className="relative border-0 shadow-lg shadow-indigo-100/50 bg-white/80 backdrop-blur-sm overflow-hidden rounded-2xl">
                    <div className="absolute top-0 right-0 p-32 bg-indigo-500/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />

                    <CardContent className="p-1 sm:p-2 md:p-8">
                        <div className="max-w-4xl mx-auto space-y-6">
                            <form onSubmit={handleTaskSubmit} className="relative z-10">
                                <div className="relative group transition-all duration-300">
                                    <div className="absolute inset-y-0 left-0 pl-6 flex items-center pointer-events-none">
                                        <Bot className="h-6 w-6 text-indigo-400 group-focus-within:text-indigo-600 transition-colors" />
                                    </div>
                                    <Input
                                        type="text"
                                        className="pl-16 pr-32 h-16 text-lg rounded-2xl border-gray-200 shadow-sm focus:border-indigo-300 focus:ring-4 focus:ring-indigo-100 transition-all w-full bg-white"
                                        placeholder="e.g. Analyze tumor regions in the latest liver slide..."
                                        value={taskInput}
                                        onChange={(e) => setTaskInput(e.target.value)}
                                        onFocus={() => navigate('/ai-chat', { state: { fromDashboard: true } })}
                                        disabled={isSubmitting}
                                    />

                                    <div className="absolute right-2 top-2 bottom-2 flex items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={toggleRecording}
                                            disabled={isSubmitting}
                                            className="p-3 h-full aspect-square flex items-center justify-center rounded-xl hover:bg-gray-100 text-gray-500 transition-all"
                                        >
                                            <Mic className="w-5 h-5" />
                                        </button>
                                        <Button
                                            type="submit"
                                            disabled={!taskInput.trim() || isSubmitting}
                                            className="h-full rounded-xl px-6 bg-indigo-600 hover:bg-indigo-700 text-white shadow-md hover:shadow-lg transition-all"
                                        >
                                            <ArrowRight className="w-5 h-5" />
                                        </Button>
                                    </div>
                                </div>
                            </form>
                        </div>
                    </CardContent>
                </Card>
            </div>

            {/* Workflow Pipeline - The "Visual Action Line" */}
            <div>
                <div className="flex items-center gap-2 mb-4 px-1">
                    <LayoutGrid className="w-4 h-4 text-gray-400" />
                    <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-widest">Workflow</h3>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {workflowModules.map((module, idx) => {
                        const Icon = module.icon
                        return (
                            <div key={idx} className={`relative group rounded-2xl border bg-white p-6 transition-all duration-300 hover:shadow-xl hover:-translate-y-1 ${module.border} ${module.ring} ring-0 hover:ring-2`}>
                                <div className={`absolute top-0 right-0 w-24 h-24 rounded-bl-full opacity-10 transition-opacity group-hover:opacity-20 ${module.bg.replace('bg-', 'bg-')}`} />

                                <div className="relative z-10 flex flex-col h-full">
                                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${module.bg} ${module.color}`}>
                                        <Icon className="w-6 h-6" />
                                    </div>

                                    <div className="mb-6 flex-1">
                                        <h4 className="text-lg font-bold text-gray-900 mb-1">{module.title}</h4>
                                        <p className="text-sm text-gray-500">{module.description}</p>
                                    </div>

                                    <div className="flex items-center gap-3 mt-auto">
                                        <Button
                                            variant="default"
                                            className={`flex-1 rounded-lg ${module.color} bg-white border border-current hover:bg-gray-50 shadow-none`}
                                            onClick={() => navigate(module.mainAction.path)}
                                        >
                                            {module.mainAction.label}
                                        </Button>

                                        {module.subAction && (
                                            <Button
                                                variant="ghost"
                                                className="px-3 text-gray-400 hover:text-gray-600"
                                                onClick={() => navigate(module.subAction.path)}
                                            >
                                                {module.subAction.label}
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Recent Activity Split */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                {/* Recent Data */}
                <div className="space-y-4">
                    <div className="flex items-center justify-between px-1">
                        <div className="flex items-center gap-2">
                            <FolderOpen className="w-4 h-4 text-gray-400" />
                            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-widest">Recent Data</h3>
                        </div>
                        <div className="flex items-center gap-2">
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-gray-400 hover:text-gray-600 rounded-full"
                                onClick={() => loadRecentActivity(true)}
                                disabled={activityLoading}
                            >
                                <RefreshCw className={`w-3.5 h-3.5 ${activityLoading ? 'animate-spin' : ''}`} />
                            </Button>
                            <Button variant="link" className="text-xs h-auto p-0 text-indigo-600" onClick={() => navigate('/wsi-list')}>
                                View all
                            </Button>
                        </div>
                    </div>

                    <Card className="border-gray-100 shadow-sm overflow-hidden">
                        <div className="divide-y divide-gray-50">
                            {activityLoading ? (
                                <div className="p-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-gray-300" /></div>
                            ) : visibleUploads.length === 0 ? (
                                <div className="p-8 text-center text-gray-400 text-sm">No recent files</div>
                            ) : (
                                visibleUploads.slice(0, 4).map((img) => (
                                    <div
                                        key={img.wsi_id}
                                        className="group p-3 flex items-center gap-3 hover:bg-blue-50/50 cursor-pointer transition-colors"
                                        onClick={() => navigate(`/wsi/${img.wsi_id}`)}
                                    >
                                        <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0 text-gray-400">
                                            <FileText className="w-5 h-5" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-medium text-gray-900 truncate">{img.original_filename}</p>
                                            <p className="text-xs text-gray-500">{formatRelativeTime(img.created_at)}</p>
                                        </div>
                                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
                                    </div>
                                ))
                            )}
                        </div>
                    </Card>
                </div>

                {/* Recent Analysis */}
                <div className="space-y-4">
                    <div className="flex items-center justify-between px-1">
                        <div className="flex items-center gap-2">
                            <Brain className="w-4 h-4 text-gray-400" />
                            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-widest">Recent Analysis</h3>
                        </div>
                        <div className="flex items-center gap-2">
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-gray-400 hover:text-gray-600 rounded-full"
                                onClick={() => loadRecentActivity(true)}
                                disabled={activityLoading}
                            >
                                <RefreshCw className={`w-3.5 h-3.5 ${activityLoading ? 'animate-spin' : ''}`} />
                            </Button>
                            <Button variant="link" className="text-xs h-auto p-0 text-indigo-600" onClick={() => navigate('/task-list')}>
                                View all
                            </Button>
                        </div>
                    </div>

                    <Card className="border-gray-100 shadow-sm overflow-hidden">
                        <div className="divide-y divide-gray-50">
                            {activityLoading ? (
                                <div className="p-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-gray-300" /></div>
                            ) : visibleTasks.length === 0 ? (
                                <div className="p-8 text-center text-gray-400 text-sm">No recent tasks</div>
                            ) : (
                                visibleTasks.slice(0, 4).map((task) => (
                                    <div
                                        key={task.task_id}
                                        className="group p-3 flex items-center gap-3 hover:bg-violet-50/50 cursor-pointer transition-colors"
                                        onClick={() => navigate(`/task/${task.task_id}`)}
                                    >
                                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 border ${task.status === 'completed' ? 'bg-emerald-50 border-emerald-100 text-emerald-600' :
                                            task.status === 'failed' ? 'bg-red-50 border-red-100 text-red-600' :
                                                'bg-yellow-50 border-yellow-100 text-yellow-600'
                                            }`}>
                                            {task.status === 'completed' ? <CheckCircle className="w-5 h-5" /> :
                                                task.status === 'failed' ? <X className="w-5 h-5" /> :
                                                    <Loader2 className="w-5 h-5 animate-spin" />}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-medium text-gray-900 truncate">{task.task_name || 'Untitled Task'}</p>
                                            <div className="flex items-center gap-2">
                                                <Badge variant="outline" className="text-[10px] px-1 py-0 border-gray-200 text-gray-500 capitalize">
                                                    {task.task_type?.replace(/_/g, ' ')}
                                                </Badge>
                                                <span className="text-xs text-gray-400">{formatRelativeTime(task.created_at)}</span>
                                            </div>
                                        </div>
                                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-violet-400 opacity-0 group-hover:opacity-100 transition-all" />
                                    </div>
                                ))
                            )}
                        </div>
                    </Card>
                </div>
            </div>

            {/* Toast notification */}
            {toastMessage && (
                <div className={`fixed bottom-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 max-w-sm sm:max-w-md animate-in slide-in-from-bottom-5 ${toastMessage.type === 'error' ? 'bg-red-500 text-white' :
                    toastMessage.type === 'success' ? 'bg-green-500 text-white' : 'bg-gray-800 text-white'
                    }`}>
                    <span className="text-sm font-medium">{toastMessage.message}</span>
                    <button
                        onClick={() => setToastMessage(null)}
                        className="ml-auto hover:opacity-80"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            )}
        </div>
    )
}
