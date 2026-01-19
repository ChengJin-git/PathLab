import { useRef, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { Download } from 'lucide-react'

interface ConfusionMatrixData {
  classes: string[]
  data: [number, number, number][] // [predIndex, trueIndex, value]
}

interface RocCurveData {
  classes: string[]
  data: Record<string, { fpr: number[]; tpr: number[]; auc: number }>
}

interface LossCurveData {
  epochs: number[]
  loss: number[]
  val_loss?: number[]
  accuracy?: number[]
  val_accuracy?: number[]
}

interface ChartProps {
  title: string
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316']

export function exportChartAsPng(chartRef: React.RefObject<ReactECharts | null>, filename: string, dpi: number = 600) {
  if (!chartRef.current) return
  const echartsInstance = chartRef.current.getEchartsInstance()
  const pixelRatio = dpi / 96
  const dataUrl = echartsInstance.getDataURL({ type: 'png', pixelRatio, backgroundColor: '#fff' })
  const link = document.createElement('a')
  link.download = filename
  link.href = dataUrl
  link.click()
}

export function ConfusionMatrixChart({ data, title }: { data: ConfusionMatrixData } & ChartProps) {
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'confusion_matrix.png', 600), [])
  const maxValue = Math.max(...data.data.map(d => d[2]))

  const option: EChartsOption = {
    title: { text: title || 'Confusion Matrix', left: 'center', textStyle: { fontSize: 16 }, top: 10 },
    tooltip: {
      position: 'top',
      formatter: (params: any) => {
        const [pred, actual, value] = params.data
        return `True: ${data.classes[actual]}<br/>Predicted: ${data.classes[pred]}<br/>Count: ${value}`
      }
    },
    grid: { left: '15%', right: '10%', top: '15%', bottom: '25%' },
    xAxis: { type: 'category', data: data.classes, name: 'Predicted Label', nameLocation: 'middle', nameGap: 30, axisLabel: { fontSize: 12 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: data.classes, name: 'True Label', nameLocation: 'middle', nameGap: 50, axisLabel: { fontSize: 12 }, splitArea: { show: true }, inverse: true },
    visualMap: { min: 0, max: maxValue || 1, calculable: true, orient: 'horizontal', left: 'center', bottom: '0', inRange: { color: ['#e0e7ff', '#3730a3'] }, itemWidth: 15, itemHeight: 200, text: ['High', 'Low'], textGap: 5 },
    series: [{ type: 'heatmap', data: data.data, label: { show: true, fontSize: 14, fontWeight: 'bold' }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } } }]
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'Confusion Matrix'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '350px', width: '100%' }} />
    </div>
  )
}

export function RocCurveChart({ data, title }: { data: RocCurveData } & ChartProps) {
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'roc_curve.png', 600), [])

  const series: any[] = data.classes.filter(cls => data.data[cls]).map((cls, i) => ({
    name: `${cls} (AUC = ${data.data[cls].auc.toFixed(3)})`,
    type: 'line', smooth: true,
    data: data.data[cls].fpr.map((fpr, j) => [fpr, data.data[cls].tpr[j]]),
    lineStyle: { width: 2, color: COLORS[i % COLORS.length] },
    itemStyle: { color: COLORS[i % COLORS.length] }, showSymbol: false
  }))
  series.push({ name: 'Random (AUC = 0.5)', type: 'line', data: [[0, 0], [1, 1]], lineStyle: { width: 1, type: 'dashed', color: '#666' }, itemStyle: { color: '#666' }, showSymbol: false })

  const option: EChartsOption = {
    title: { text: title || 'ROC Curve', left: 'center', textStyle: { fontSize: 16 }, top: 10 },
    tooltip: { trigger: 'axis', formatter: (params: any) => {
      const lines = params.map((p: any) => `${p.seriesName}: TPR=${p.data[1]?.toFixed(3)}`)
      return `FPR: ${params[0]?.data[0]?.toFixed(3)}<br/>${lines.join('<br/>')}`
    }},
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: '12%', right: '10%', top: '15%', bottom: '30%' },
    xAxis: { type: 'value', name: 'False Positive Rate', min: 0, max: 1, nameLocation: 'middle', nameGap: 30 },
    yAxis: { type: 'value', name: 'True Positive Rate', min: 0, max: 1, nameLocation: 'middle', nameGap: 40 },
    series
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'ROC Curve'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '350px', width: '100%' }} />
    </div>
  )
}

export function LossCurveChart({ data, title }: { data: LossCurveData } & ChartProps) {
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'loss_curve.png', 600), [])

  const series: any[] = [{ name: 'Training Loss', type: 'line', data: data.epochs.map((epoch, i) => [epoch, data.loss[i]]), lineStyle: { width: 2, color: COLORS[0] }, itemStyle: { color: COLORS[0] }, showSymbol: false, smooth: true }]
  if (data.val_loss && data.val_loss.length > 0) {
    series.push({ name: 'Validation Loss', type: 'line', data: data.epochs.slice(0, data.val_loss.length).map((epoch, i) => [epoch, data.val_loss![i]]), lineStyle: { width: 2, type: 'dashed', color: COLORS[3] }, itemStyle: { color: COLORS[3] }, showSymbol: false, smooth: true })
  }

  const option: EChartsOption = {
    title: { text: title || 'Training Loss Curve', left: 'center', textStyle: { fontSize: 16 }, top: 10 },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 5, textStyle: { fontSize: 11 } },
    grid: { left: '12%', right: '10%', top: '15%', bottom: '25%' },
    xAxis: { type: 'value', name: 'Epoch', nameLocation: 'middle', nameGap: 30, min: 1 },
    yAxis: { type: 'value', name: 'Loss', nameLocation: 'middle', nameGap: 40 },
    series
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'Loss Curve'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '350px', width: '100%' }} />
    </div>
  )
}

export type { ConfusionMatrixData, RocCurveData, LossCurveData }