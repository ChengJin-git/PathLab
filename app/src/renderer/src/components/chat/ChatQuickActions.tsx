import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import * as Dialog from '@radix-ui/react-dialog'
import { ArrowUpRight, Ellipsis, Sparkles, X } from 'lucide-react'
import { SCENARIO_CARDS } from '../../constants/scenarios'
import { Button } from '../ui/button'

export default function ChatQuickActions({
  centered,
  canResearch,
  onScenario,
  onResearch,
}: {
  centered: boolean
  canResearch: boolean
  onScenario: (card: (typeof SCENARIO_CARDS)[number]) => void
  onResearch: () => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const primary = SCENARIO_CARDS.find(
    (card) => card.id === (canResearch ? 'train-model' : 'browse-images'),
  )!
  const choose = (action: () => void) => {
    setOpen(false)
    action()
  }
  return (
    <div className="mb-2 flex min-w-0 items-center gap-1.5 sm:flex-wrap sm:gap-2">
      {SCENARIO_CARDS.map((card) => {
        const Icon = card.icon
        return (
          <Button
            key={card.id}
            type="button"
            size="sm"
            variant="outline"
            className={`${centered && card.id === primary.id ? 'inline-flex' : 'hidden'} h-8 min-w-0 gap-1.5 px-2.5 text-left sm:inline-flex sm:h-9 sm:min-h-9 sm:gap-2 sm:whitespace-normal sm:px-3`}
            onClick={() => onScenario(card)}
          >
            <Icon size={15} className={`shrink-0 ${card.iconColor}`} />
            <span>{t(card.titleKey)}</span>
          </Button>
        )
      })}
      {canResearch && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          title={t('aiChat.sidebar.autoExperimentHint')}
          className={`${centered ? 'inline-flex' : 'hidden'} h-8 min-w-0 gap-1.5 px-2.5 text-left sm:inline-flex sm:h-9 sm:min-h-9 sm:gap-2 sm:whitespace-normal sm:px-3`}
          onClick={onResearch}
        >
          <Sparkles size={15} className="shrink-0" />
          <span>{t('aiChat.sidebar.autoExperiment')}</span>
        </Button>
      )}
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Trigger asChild>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-8 shrink-0 gap-1.5 px-2 text-slate-500 sm:hidden"
            aria-label={t('aiChat.quickActions')}
          >
            <Ellipsis size={18} />
            {!centered && t('aiChat.quickActions')}
          </Button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[100] bg-black/30 sm:hidden" />
          <Dialog.Content
            className="fixed inset-x-0 bottom-0 z-[101] rounded-t-2xl bg-white px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 shadow-xl sm:hidden"
            aria-describedby={undefined}
          >
            <div className="mb-1 flex items-center justify-between px-2">
              <Dialog.Title className="text-sm font-semibold text-slate-900">
                {t('aiChat.quickActions')}
              </Dialog.Title>
              <Dialog.Close asChild>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8"
                  aria-label={t('common.close')}
                >
                  <X size={18} />
                </Button>
              </Dialog.Close>
            </div>
            <div className="space-y-0.5">
              {SCENARIO_CARDS.map((card) => {
                const Icon = card.icon
                return (
                  <button
                    key={card.id}
                    type="button"
                    onClick={() => choose(() => onScenario(card))}
                    className="flex min-h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-primary-500"
                  >
                    <Icon size={16} className={`shrink-0 ${card.iconColor}`} />
                    <span className="flex-1">{t(card.titleKey)}</span>
                    <ArrowUpRight size={15} className="text-slate-400" />
                  </button>
                )
              })}
              {canResearch && (
                <button
                  type="button"
                  onClick={() => choose(onResearch)}
                  className="flex min-h-10 w-full items-center gap-2 rounded-lg bg-primary-50 px-2 py-2 text-left text-sm text-primary-700"
                >
                  <Sparkles size={16} />
                  <span className="flex-1">
                    {t('aiChat.sidebar.autoExperiment')}
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}
