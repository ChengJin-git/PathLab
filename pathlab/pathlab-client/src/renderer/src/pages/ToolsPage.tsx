import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Rocket, TrendingUp, FileText, ChevronRight } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'

export default function ToolsPage() {
    const navigate = useNavigate()

    const tools = [
        {
            title: 'Custom Analysis',
            description: 'Configure and run specific AI models manually.',
            icon: Rocket,
            path: '/task-setup',
            color: 'text-rose-500',
        },
        {
            title: 'Results Viewer',
            description: 'Explore detailed heatmaps and classification results.',
            icon: TrendingUp,
            path: '/results',
            color: 'text-indigo-500',
        },
        {
            title: 'Report Generator',
            description: 'Create PDF reports from your analysis data.',
            icon: FileText,
            path: '/reports',
            color: 'text-emerald-500',
        },
    ]

    return (
        <div className="w-full py-8">
            <PageHeader
                title="Advanced Tools"
                description="Access powerful research tools and configuration options."
            />

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {tools.map((tool, index) => {
                    const Icon = tool.icon
                    return (
                        <Card key={index} className="group hover:shadow-lg transition-all duration-300 ease-out cursor-pointer border-gray-200 hover:border-blue-100" onClick={() => navigate(tool.path)}>
                            <CardHeader className="flex flex-row items-center gap-4 space-y-0 pb-2">
                                <div className={`p-2 bg-gray-50 rounded-xl ${tool.color} transition-transform duration-300 group-hover:scale-110`}>
                                    <Icon className="w-6 h-6" />
                                </div>
                                <CardTitle className="text-xl text-gray-900 group-hover:text-blue-600 transition-colors">{tool.title}</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <CardDescription className="text-base text-gray-500 leading-relaxed">{tool.description}</CardDescription>
                                <div className="mt-5 flex items-center text-sm font-semibold text-blue-600">
                                    Open Tool 
                                    <ChevronRight className="w-4 h-4 ml-1 transition-transform duration-300 group-hover:translate-x-1" />
                                </div>
                            </CardContent>
                        </Card>
                    )
                })}
            </div>
        </div>
    )
}
