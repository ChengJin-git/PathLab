import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchStats } from '../api'

interface Stats {
  wsi_count: number
  task_count: number
  completed_count: number
  results_count: number
  labels: Record<string, number>
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  const runningCount = stats ? stats.task_count - stats.completed_count : 0

  const statCards = [
    {
      title: 'Total WSI Files',
      value: stats?.wsi_count || 0,
      icon: '🔬',
      color: 'from-blue-500 to-blue-600',
      bgColor: 'bg-blue-50',
      textColor: 'text-blue-700',
    },
    {
      title: 'Completed Tasks',
      value: stats?.completed_count || 0,
      icon: '✅',
      color: 'from-green-500 to-green-600',
      bgColor: 'bg-green-50',
      textColor: 'text-green-700',
    },
    {
      title: 'Running Tasks',
      value: runningCount,
      icon: '⚙️',
      color: 'from-orange-500 to-orange-600',
      bgColor: 'bg-orange-50',
      textColor: 'text-orange-700',
    },
    {
      title: 'Analysis Results',
      value: stats?.results_count || 0,
      icon: '📊',
      color: 'from-purple-500 to-purple-600',
      bgColor: 'bg-purple-50',
      textColor: 'text-purple-700',
    },
  ]

  const quickActions = [
    {
      title: 'New Task',
      description: 'Start a new research task',
      icon: '🚀',
      path: '/task-setup',
      color: 'from-primary-500 to-primary-600',
    },
    {
      title: 'Browse WSI',
      description: 'View all WSI files',
      icon: '📁',
      path: '/wsi-list',
      color: 'from-indigo-500 to-indigo-600',
    },
    {
      title: 'Select Data',
      description: 'Choose training data',
      icon: '🎯',
      path: '/training-data-selection',
      color: 'from-pink-500 to-pink-600',
    },
    {
      title: 'Inference',
      description: 'Run model inference',
      icon: '🔍',
      path: '/inference',
      color: 'from-teal-500 to-teal-600',
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Dashboard</h1>
        <p className="text-gray-600">Welcome to SmartResearch - Your AI-powered pathology research platform</p>
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
            {statCards.map((card, index) => (
              <div
                key={index}
                className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-600 mb-1">{card.title}</p>
                    <p className="text-3xl font-bold text-gray-900">{card.value}</p>
                  </div>
                  <div className={`w-14 h-14 rounded-lg bg-gradient-to-br ${card.color} flex items-center justify-center text-2xl shadow-lg`}>
                    {card.icon}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Quick Actions */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-bold text-gray-900 mb-4">Quick Actions</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {quickActions.map((action, index) => (
                <button
                  key={index}
                  onClick={() => navigate(action.path)}
                  className="group relative overflow-hidden bg-gradient-to-br from-gray-50 to-gray-100 hover:from-white hover:to-gray-50 border border-gray-200 rounded-lg p-6 text-left transition-all hover:shadow-md hover:scale-105"
                >
                  <div className={`absolute top-0 right-0 w-20 h-20 bg-gradient-to-br ${action.color} opacity-10 rounded-bl-full`}></div>
                  <div className="text-3xl mb-3">{action.icon}</div>
                  <h3 className="font-semibold text-gray-900 mb-1">{action.title}</h3>
                  <p className="text-sm text-gray-600">{action.description}</p>
                </button>
              ))}
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

