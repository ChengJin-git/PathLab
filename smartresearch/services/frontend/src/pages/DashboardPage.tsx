import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats } from '../api'
import { Microscope, CheckCircle, Settings as SettingsIcon, BarChart3, Bot, Rocket, ClipboardList, FolderOpen, Database, Settings } from 'lucide-react'

interface Stats {
  wsi_count: number
  task_count: number
  completed_count: number
  results_count: number
  labels: Record<string, number>
}

interface StatCard {
  title: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  color: string
  bgColor: string
  textColor: string
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
    // Refresh stats every 5 seconds
    const interval = setInterval(loadStats, 5000)
    return () => clearInterval(interval)
  }, [])

  const loadStats = async () => {
    try {
      const data = await fetchStats()
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
      alert('Failed to submit task: ' + String(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  const runningCount = stats ? stats.task_count - stats.completed_count : 0

  const statCards: StatCard[] = [
    {
      title: 'Total Slides',
      value: stats?.wsi_count || 0,
      icon: Microscope,
      color: 'from-blue-500 to-blue-600',
      bgColor: 'bg-blue-50',
      textColor: 'text-blue-700',
    },
    {
      title: 'Completed',
      value: stats?.completed_count || 0,
      icon: CheckCircle,
      color: 'from-green-500 to-green-600',
      bgColor: 'bg-green-50',
      textColor: 'text-green-700',
    },
    {
      title: 'In Progress',
      value: runningCount,
      icon: SettingsIcon,
      color: 'from-orange-500 to-orange-600',
      bgColor: 'bg-orange-50',
      textColor: 'text-orange-700',
    },
    {
      title: 'Results',
      value: stats?.results_count || 0,
      icon: BarChart3,
      color: 'from-purple-500 to-purple-600',
      bgColor: 'bg-purple-50',
      textColor: 'text-purple-700',
    },
  ]

  const quickActions: QuickAction[] = [
    {
      title: 'New Task',
      description: 'Let AI help you analyze slides',
      icon: Bot,
      path: '/ai-chat',
      color: 'from-purple-500 to-purple-600',
    },
    {
      title: 'Custom Setup',
      description: 'Manually configure your analysis',
      icon: Rocket,
      path: '/task-setup',
      color: 'from-pink-500 to-rose-600',
    },
    {
      title: 'Task Browser',
      description: 'Monitor your analysis tasks',
      icon: ClipboardList,
      path: '/task-list',
      color: 'from-blue-500 to-blue-600',
    },
    {
      title: 'Slide Browser',
      description: 'Explore your slide collection',
      icon: FolderOpen,
      path: '/wsi-list',
      color: 'from-amber-500 to-orange-600',
    },
    {
      title: 'Checkpoint Manager',
      description: 'Manage model checkpoints',
      icon: Database,
      path: '/checkpoint-manager',
      color: 'from-teal-500 to-cyan-600',
    },
    {
      title: 'Settings',
      description: 'Adjust your preferences',
      icon: Settings,
      path: '/settings',
      color: 'from-gray-500 to-gray-600',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Dashboard</h1>
        <p className="text-gray-600">Welcome to SmartResearch - Your AI-powered pathology research platform</p>
      </div>

      {/* Task Input Bar */}
      <div className="bg-gradient-to-r from-primary-50 to-secondary-50 rounded-xl shadow-sm border border-primary-200 p-6">
        <form onSubmit={handleTaskSubmit}>
          <div className="flex items-center space-x-4">
            <div className="flex-shrink-0 w-12 h-12 bg-gradient-to-br from-primary-500 to-secondary-500 rounded-lg flex items-center justify-center text-white shadow-lg">
              <Bot className="w-7 h-7" />
            </div>
            <div className="flex-1">
              <input
                id="task-input"
                type="text"
                value={taskInput}
                onChange={(e) => setTaskInput(e.target.value)}
                placeholder="Tell me what you want to research, e.g., Classify HSIL and LSIL samples using deep learning..."
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent transition-all text-gray-900 placeholder-gray-400"
                disabled={isSubmitting}
              />
            </div>
            <button
              type="submit"
              disabled={!taskInput.trim() || isSubmitting}
              className="flex-shrink-0 px-6 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg whitespace-nowrap"
            >
              {isSubmitting ? (
                <span className="flex items-center space-x-2">
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>Processing...</span>
                </span>
              ) : (
                '🚀 Submit Task'
              )}
            </button>
          </div>
        </form>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          <p className="font-medium">Error loading statistics</p>
          <p className="text-sm">{error}</p>
        </div>
      )}

      {!loading && stats && (
        <>
          {/* Statistics Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {statCards.map((card, index) => {
              const Icon = card.icon
              return (
                <div
                  key={index}
                  className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-600 mb-1">{card.title}</p>
                      <p className="text-3xl font-bold text-gray-900">{card.value}</p>
                    </div>
                    <div className={`w-14 h-14 rounded-lg bg-gradient-to-br ${card.color} flex items-center justify-center shadow-lg`}>
                      <Icon className="w-7 h-7 text-white" />
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Quick Actions */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Quick Actions</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {quickActions.map((action, index) => {
                const Icon = action.icon
                return (
                  <button
                    key={index}
                    onClick={() => navigate(action.path)}
                    className="group relative overflow-hidden bg-gradient-to-br from-gray-50 to-gray-100 hover:from-white hover:to-gray-50 border border-gray-200 rounded-lg p-6 text-left transition-all hover:shadow-md hover:scale-105"
                  >
                    <div className={`absolute top-0 right-0 w-20 h-20 bg-gradient-to-br ${action.color} opacity-10 rounded-bl-full`}></div>
                    <div className="mb-3">
                      <Icon className="w-8 h-8 text-gray-700" />
                    </div>
                    <h3 className="font-semibold text-gray-900 mb-1">{action.title}</h3>
                    <p className="text-sm text-gray-600">{action.description}</p>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Label Distribution */}
          {Object.keys(stats.labels).length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h2 className="text-xl font-bold text-gray-900 mb-4">Label Distribution</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {Object.entries(stats.labels).map(([label, count]) => {
                  const percentage = ((count / stats.wsi_count) * 100).toFixed(1)
                  return (
                    <div key={label} className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-gray-900">{label}</span>
                        <span className="text-sm text-gray-600">{count} samples</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2.5 mb-1">
                        <div
                          className="bg-gradient-to-r from-primary-500 to-secondary-500 h-2.5 rounded-full transition-all duration-500"
                          style={{ width: `${percentage}%` }}
                        ></div>
                      </div>
                      <p className="text-xs text-gray-500">{percentage}% of total</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* System Status */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">System Status</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {['Gateway Service', 'WSI Service', 'AI Service'].map((service) => (
                <div key={service} className="flex items-center space-x-3 bg-green-50 rounded-lg p-4 border border-green-200">
                  <div className="relative">
                    <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                    <div className="absolute top-0 left-0 w-3 h-3 bg-green-500 rounded-full animate-ping"></div>
                  </div>
                  <div>
                    <p className="font-medium text-gray-900">{service}</p>
                    <p className="text-xs text-green-700">Online</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Activity */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Recent Activity</h2>
            <div className="space-y-3">
              <div className="flex items-start space-x-3 p-3 bg-blue-50 rounded-lg border border-blue-100">
                <div className="text-2xl">📊</div>
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900">System initialized successfully</p>
                  <p className="text-xs text-gray-600">All services are running normally</p>
                </div>
                <span className="text-xs text-gray-500">Just now</span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

