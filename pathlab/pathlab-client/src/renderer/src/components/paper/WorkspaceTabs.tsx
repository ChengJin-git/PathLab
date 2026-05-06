import * as Tabs from '@radix-ui/react-tabs'
import { BookOpen, FileCode2, FileJson, Image, Library, ShieldCheck, Table2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PaperRunDetail } from '../../api/papers'
import { CitationsTab } from './CitationsTab'
import { FiguresTab } from './FiguresTab'
import { OutlineTab } from './OutlineTab'
import { PdfPreviewTab } from './PdfPreviewTab'
import { SectionsTab } from './SectionsTab'
import { TablesTab } from './TablesTab'
import { ValidationTab } from './ValidationTab'

export const WORKSPACE_TAB_VALUES = ['outline', 'sections', 'figures', 'tables', 'citations', 'validation', 'pdf'] as const
export type WorkspaceTabValue = (typeof WORKSPACE_TAB_VALUES)[number]

interface WorkspaceTabsProps {
  paperId: string
  run: PaperRunDetail
  value: WorkspaceTabValue
  onValueChange: (value: WorkspaceTabValue) => void
}

interface TabDefinition {
  value: WorkspaceTabValue
  label: string
  icon: LucideIcon
}

const TABS: TabDefinition[] = [
  { value: 'outline', label: 'Outline', icon: FileJson },
  { value: 'sections', label: 'Sections', icon: FileCode2 },
  { value: 'figures', label: 'Figures', icon: Image },
  { value: 'tables', label: 'Tables', icon: Table2 },
  { value: 'citations', label: 'Citations', icon: Library },
  { value: 'validation', label: 'Validation', icon: ShieldCheck },
  { value: 'pdf', label: 'PDF Preview', icon: BookOpen },
]

function isWorkspaceTabValue(value: string): value is WorkspaceTabValue {
  return (WORKSPACE_TAB_VALUES as readonly string[]).includes(value)
}

export function coerceWorkspaceTab(value: string | null | undefined): WorkspaceTabValue {
  if (value === 'pdf_preview' || value === 'pdf-preview') return 'pdf'
  return value && isWorkspaceTabValue(value) ? value : 'outline'
}

export function WorkspaceTabs({ paperId, run, value, onValueChange }: WorkspaceTabsProps) {
  return (
    <Tabs.Root
      value={value}
      onValueChange={(next) => {
        if (isWorkspaceTabValue(next)) onValueChange(next)
      }}
      className="overflow-hidden rounded-[1.75rem] border border-slate-200 bg-white shadow-sm"
    >
      <div className="border-b border-slate-100 bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.12),_transparent_34%),linear-gradient(180deg,_#ffffff,_#f8fafc)] p-2">
        <Tabs.List className="flex gap-1 overflow-x-auto rounded-[1.25rem] bg-white/70 p-1 shadow-inner shadow-slate-200/60" aria-label="Paper workspace tabs">
          {TABS.map((tab) => {
            const Icon = tab.icon
            return (
              <Tabs.Trigger
                key={tab.value}
                value={tab.value}
                className={cn(
                  'inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-500 transition data-[state=active]:bg-slate-950 data-[state=active]:text-white data-[state=active]:shadow-sm sm:text-sm',
                  'focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-sky-500/20'
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </Tabs.Trigger>
            )
          })}
        </Tabs.List>
      </div>

      <Tabs.Content value="outline" className="p-4 focus:outline-none sm:p-5">
        <OutlineTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="sections" className="p-4 focus:outline-none sm:p-5">
        <SectionsTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="figures" className="p-4 focus:outline-none sm:p-5">
        <FiguresTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="tables" className="p-4 focus:outline-none sm:p-5">
        <TablesTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="citations" className="p-4 focus:outline-none sm:p-5">
        <CitationsTab paperId={paperId} />
      </Tabs.Content>
      <Tabs.Content value="validation" className="p-4 focus:outline-none sm:p-5">
        <ValidationTab paperId={paperId} validationSummary={run.validation_summary ?? null} />
      </Tabs.Content>
      <Tabs.Content value="pdf" className="p-4 focus:outline-none sm:p-5">
        <PdfPreviewTab paperId={paperId} run={run} />
      </Tabs.Content>
    </Tabs.Root>
  )
}
