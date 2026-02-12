import { HeatmapData } from '../../api'
import { Card } from '../common'
import { Layers, ChevronDown, CheckCircle2 } from 'lucide-react'

interface AttentionClassSelectorProps {
  heatmapData: HeatmapData
  selectedClassIdx: number | undefined
  setSelectedClassIdx: (idx: number) => void
  isClassDropdownOpen: boolean
  setIsClassDropdownOpen: (open: boolean) => void
}

export function AttentionClassSelector({
  heatmapData,
  selectedClassIdx,
  setSelectedClassIdx,
  isClassDropdownOpen,
  setIsClassDropdownOpen
}: AttentionClassSelectorProps) {
  return (
    <Card className="mb-4 overflow-visible">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-purple-50 to-white">
        <Layers className="w-4 h-4 text-purple-500" />
        <h3 className="m-0 text-sm font-semibold text-gray-900">Attention Class</h3>
        <span className="ml-auto text-xs text-gray-500 bg-purple-100 px-2 py-0.5 rounded">
          {heatmapData.aggregator || 'multi-class'}
        </span>
      </div>
      <div className="p-3 relative">
        <div className="relative">
          <button
            onClick={() => setIsClassDropdownOpen(!isClassDropdownOpen)}
            className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-lg shadow-sm transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-purple-500/10 active:scale-[0.99] group ${isClassDropdownOpen ? 'border-purple-500 ring-4 ring-purple-500/10' : 'border-gray-200 hover:border-purple-300 hover:shadow-md'
              }`}
          >
            <div className="flex flex-col items-start gap-1">
              <span className="text-gray-900 font-semibold text-sm tracking-tight text-left">
                {selectedClassIdx !== undefined && heatmapData.classes[selectedClassIdx]
                  ? heatmapData.classes[selectedClassIdx]
                  : 'Select a class...'}
              </span>
              <span className="text-xs text-gray-500">
                Class {(selectedClassIdx ?? 0) + 1} of {heatmapData.num_attention_classes}
              </span>
            </div>
            <ChevronDown
              className={`w-4 h-4 text-gray-400 transition-transform duration-300 ease-in-out group-hover:text-purple-500 ${isClassDropdownOpen ? 'rotate-180 text-purple-500' : ''
                }`}
            />
          </button>

          {isClassDropdownOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setIsClassDropdownOpen(false)}
              />
              <div className="absolute z-20 w-full mt-2 bg-white/90 backdrop-blur-xl border border-white/20 rounded-xl shadow-2xl shadow-purple-500/10 overflow-hidden animate-in fade-in zoom-in-95 duration-200 origin-top ring-1 ring-black/5">
                <div className="max-h-[320px] overflow-y-auto py-2 scrollbar-thin scrollbar-thumb-gray-200">
                  {heatmapData.classes.map((cls, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        setSelectedClassIdx(idx)
                        setIsClassDropdownOpen(false)
                      }}
                      className="w-full text-left px-2 py-1 mx-2 rounded-lg transition-all duration-200 group/item flex items-center mb-1 last:mb-0 relative overflow-hidden max-w-[calc(100%-16px)]"
                    >
                      <div className={`absolute inset-0 transition-opacity duration-200 ${selectedClassIdx === idx
                        ? 'bg-purple-600 opacity-100'
                        : 'bg-gray-50 opacity-0 group-hover/item:opacity-100'
                        }`} />

                      <div className="relative z-10 w-full px-3 py-2.5 flex items-center justify-between">
                        <div className="flex flex-col gap-1">
                          <span className={`text-[13px] font-semibold tracking-tight transition-colors duration-200 ${selectedClassIdx === idx ? 'text-white' : 'text-gray-700'
                            }`}>
                            {cls}
                          </span>
                          <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full w-fit transition-colors duration-200 ${selectedClassIdx === idx
                            ? 'bg-white/20 text-white'
                            : 'bg-purple-50 text-purple-700'
                            }`}>
                            Class {idx + 1}
                          </span>
                        </div>
                        {selectedClassIdx === idx && (
                          <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-500">
          Select which class's attention to visualize on the slide.
        </p>
      </div>
    </Card>
  )
}

