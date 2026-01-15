import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Rocket, TrendingUp, FileText } from 'lucide-react'
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
                        <Card key={index} className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => navigate(tool.path)}>
                            <CardHeader className="flex flex-row items-center gap-4 space-y-0 pb-2">
                                <div className={`p-2 bg-gray-50 rounded-lg ${tool.color}`}>
                                    <Icon className="w-6 h-6" />
                                </div>
                                <CardTitle className="text-xl">{tool.title}</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <CardDescription className="text-base">{tool.description}</CardDescription>
                                <div className="mt-4">
                                    <Button variant="ghost" className="p-0 h-auto text-primary-600 hover:text-primary-700 hover:bg-transparent">
                                        Open Tool →
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    )
                })}
            </div>
        </div>
    )
}
