import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats } from '../api'
import { Microscope, CheckCircle, Settings as SettingsIcon, BarChart3, Bot, Rocket, ClipboardList, FolderOpen, Settings, TrendingUp, FileText, Upload, LayoutGrid } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '../components/ui/card'
import { Input } from '../components/ui/input'
import { Badge } from '../components/ui/badge'

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
            title: 'Analysis History',
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
        <div className="flex-1 flex flex-col justify-center space-y-12 w-full">
            {/* Header */}
            <div className="space-y-2 text-center">
                <h1 className="text-4xl font-bold tracking-tight text-gray-900">{greeting()}, Researcher</h1>
                <p className="text-lg text-gray-600">
                    Ready to discover precise pathology insights today?
                </p>
            </div>

            {/* Main Focus: AI Assistant */}
            <Card className="border-primary-100 shadow-md bg-gradient-to-br from-white to-primary-50/30 overflow-hidden transform hover:scale-[1.01] transition-transform duration-300">
                <CardContent className="p-6 md:p-10">
                    <div className="flex flex-col items-center justify-center space-y-8 text-center">
                        {/* Added mb-8 to push it up further from the text below */}
                        <div className="w-20 h-20 bg-primary-100 rounded-2xl flex items-center justify-center mb-8 animate-bounce-slow shadow-lg shadow-primary-200">
                            <Bot className="w-10 h-10 text-primary-600" />
                        </div>
                        <div className="space-y-3 max-w-2xl">
                            <h2 className="text-3xl font-semibold text-gray-900">What would you like to research?</h2>
                            <p className="text-gray-500 text-lg">I can help you classify tumors, segment cells, or analyze WSI patterns.</p>
                        </div>

                        <form onSubmit={handleTaskSubmit} className="w-full max-w-3xl relative">
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-6 flex items-center pointer-events-none">
                                    <Bot className="h-6 w-6 text-gray-400 group-focus-within:text-primary-500 transition-colors" />
                                </div>
                                <Input
                                    type="text"
                                    className="pl-16 pr-40 h-20 text-xl rounded-2xl border-gray-200 shadow-sm focus:ring-primary-500 py-4 transition-all"
                                    placeholder="e.g. Detect tumor regions in breast cancer slides..."
                                    value={taskInput}
                                    onChange={(e) => setTaskInput(e.target.value)}
                                    disabled={isSubmitting}
                                    autoFocus
                                />
                                <div className="absolute right-3 top-3 bottom-3">
                                    <Button
                                        type="submit"
                                        disabled={!taskInput.trim() || isSubmitting}
                                        size="lg"
                                        className="h-full rounded-xl px-8 text-lg"
                                    >
                                        {isSubmitting ? 'Thinking...' : 'Start Research'}
                                    </Button>
                                </div>
                            </div>
                        </form>
                    </div>
                </CardContent>
            </Card>

            {/* Quick Actions Grid */}
            <div className="space-y-6">
                <div className="text-center">
                    <h3 className="text-xl font-semibold text-gray-900">Quick Actions</h3>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {quickActions.map((action, index) => {
                        const Icon = action.icon
                        return (
                            <Card
                                key={index}
                                className="group cursor-pointer hover:border-primary-200 hover:shadow-lg transition-all active:scale-95 bg-white/50 hover:bg-white"
                                onClick={() => navigate(action.path)}
                            >
                                <CardContent className="p-6 flex flex-col items-center text-center space-y-4">
                                    <div className={`p-4 rounded-full bg-gray-50 group-hover:bg-primary-50 transition-colors border border-gray-100 group-hover:border-primary-100`}>
                                        <Icon className={`w-8 h-8 ${action.color}`} />
                                    </div>
                                    <div>
                                        <h4 className="font-semibold text-lg text-gray-900">{action.title}</h4>
                                        <p className="text-sm text-gray-500 mt-2 leading-snug">{action.description}</p>
                                    </div>
                                </CardContent>
                            </Card>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
