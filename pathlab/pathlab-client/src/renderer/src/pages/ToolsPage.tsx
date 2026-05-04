import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Rocket, TrendingUp, FileText, ChevronRight, ArrowLeft, ScrollText } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { useAuth } from '../contexts/AuthContext'

interface Tool {
    title: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    path: string
    color: string
    comingSoon?: boolean
    requiresGpu?: boolean
}

export default function ToolsPage() {
    const navigate = useNavigate()
    const { t } = useTranslation()
    const { canUseGpu } = useAuth()

    const tools: Tool[] = [
        {
            title: t('toolsPage.tools.customAnalysis'),
            description: t('toolsPage.tools.customAnalysisDesc'),
            icon: Rocket,
            path: '/task-setup',
            color: 'text-rose-500',
            requiresGpu: true,
        },
        {
            title: t('toolsPage.tools.resultsViewer'),
            description: t('toolsPage.tools.resultsViewerDesc'),
            icon: TrendingUp,
            path: '/results',
            color: 'text-indigo-500',
            requiresGpu: true,
        },
        {
            title: t('toolsPage.tools.reportGenerator'),
            description: t('toolsPage.tools.reportGeneratorDesc'),
            icon: FileText,
            path: '/reports',
            color: 'text-emerald-500',
            comingSoon: true,
        },
        {
            title: 'Paper Generator',
            description: 'Generate manuscript drafts from completed PathLab experiments.',
            icon: ScrollText,
            path: '/papers',
            color: 'text-sky-500',
        },
    ]

    return (
        <div className="w-full py-4 sm:py-8 px-4 sm:px-6 max-w-7xl mx-auto flex flex-col h-full overflow-hidden">
            <div className="mb-4 sm:mb-8">
                <PageHeader
                    title={t('toolsPage.title')}
                    description={t('toolsPage.description')}
                >
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => navigate('/dashboard')}
                        className="gap-2 w-full sm:w-auto"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        {t('toolsPage.backToDashboard')}
                    </Button>
                </PageHeader>
            </div>

            <div className="flex-1 overflow-y-auto pr-1 flex flex-col custom-scrollbar">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
                    {tools.map((tool, index) => {
                        const Icon = tool.icon
                        const isDisabled = Boolean(tool.comingSoon || (tool.requiresGpu && !canUseGpu))
                        return (
                            <Card
                                key={index}
                                className={`group transition-all duration-300 ease-out border-gray-200 bg-white rounded-2xl overflow-hidden shadow-sm flex flex-col h-full ${
                                    isDisabled
                                        ? 'opacity-60 cursor-not-allowed'
                                        : 'hover:shadow-lg cursor-pointer hover:border-primary-200'
                                }`}
                                onClick={() => !isDisabled && navigate(tool.path)}
                            >
                                <CardHeader className="flex flex-row items-center gap-3 sm:gap-4 space-y-0 pb-3 sm:pb-4">
                                    <div className={`p-2 sm:p-2.5 bg-gray-50 rounded-xl ${isDisabled ? 'text-gray-400' : tool.color} transition-transform duration-300 ${!isDisabled && 'group-hover:scale-110'} shadow-sm`}>
                                        <Icon className="w-5 h-5 sm:w-6 sm:h-6" />
                                    </div>
                                    <div className="flex items-center gap-2 flex-1">
                                        <CardTitle className={`text-lg sm:text-xl font-bold tracking-tight ${isDisabled ? 'text-gray-400' : 'text-gray-900 group-hover:text-primary-600'} transition-colors`}>{tool.title}</CardTitle>
                                        {isDisabled && (
                                            <span className="inline-flex items-center rounded-full bg-orange-50 px-2.5 py-1 text-xs font-medium text-orange-400 ring-1 ring-inset ring-orange-200">
                                                {t('toolsPage.comingSoon')}
                                            </span>
                                        )}
                                    </div>
                                </CardHeader>
                                <CardContent className="flex-1 flex flex-col">
                                    <CardDescription className="text-xs sm:text-sm text-gray-500 leading-relaxed font-medium mb-4">{tool.description}</CardDescription>
                                    <div className="mt-auto flex items-center justify-end">
                                        <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center transition-all shadow-sm ${
                                            isDisabled
                                                ? 'bg-gray-100 text-gray-400'
                                                : 'bg-primary-50 text-primary-600 group-hover:bg-primary-600 group-hover:text-white'
                                        }`}>
                                            <ChevronRight className={`w-4 h-4 transition-transform duration-300 ${!isDisabled && 'group-hover:translate-x-0.5'}`} />
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
