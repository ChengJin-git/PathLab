import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Rocket, TrendingUp, FileText, ChevronRight, ArrowLeft } from 'lucide-react'
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
        <div className="w-full py-4 sm:py-8 px-4 sm:px-6 max-w-7xl mx-auto flex flex-col h-full overflow-hidden">
            <div className="mb-4 sm:mb-8">
                <PageHeader
                    title="Insights & Reports"
                    description="Visualize findings and generate reports."
                >
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => navigate('/dashboard')}
                        className="gap-2 w-full sm:w-auto"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        Back to Dashboard
                    </Button>
                </PageHeader>
            </div>

            <div className="flex-1 overflow-y-auto pr-1 flex flex-col custom-scrollbar">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
                    {tools.map((tool, index) => {
                        const Icon = tool.icon
                        return (
                            <Card key={index} className="group hover:shadow-lg transition-all duration-300 ease-out cursor-pointer border-gray-200 hover:border-primary-200 bg-white rounded-2xl overflow-hidden shadow-sm flex flex-col h-full" onClick={() => navigate(tool.path)}>
                                <CardHeader className="flex flex-row items-center gap-3 sm:gap-4 space-y-0 pb-3 sm:pb-4">
                                    <div className={`p-2 sm:p-2.5 bg-gray-50 rounded-xl ${tool.color} transition-transform duration-300 group-hover:scale-110 shadow-sm`}>
                                        <Icon className="w-5 h-5 sm:w-6 sm:h-6" />
                                    </div>
                                    <CardTitle className="text-lg sm:text-xl font-bold text-gray-900 group-hover:text-primary-600 transition-colors tracking-tight">{tool.title}</CardTitle>
                                </CardHeader>
                                <CardContent className="flex-1 flex flex-col">
                                    <CardDescription className="text-xs sm:text-sm text-gray-500 leading-relaxed font-medium mb-4">{tool.description}</CardDescription>
                                    <div className="mt-auto flex items-center justify-end">
                                        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-primary-50 flex items-center justify-center text-primary-600 transition-all group-hover:bg-primary-600 group-hover:text-white shadow-sm">
                                            <ChevronRight className="w-4 h-4 transition-transform duration-300 group-hover:translate-x-0.5" />
                                        </div>
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
