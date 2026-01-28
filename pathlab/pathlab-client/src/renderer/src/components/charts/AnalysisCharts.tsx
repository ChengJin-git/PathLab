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

interface KFoldLossCurveData {
  is_kfold: true
  num_folds: number
  folds: Record<string, {
    epochs: number[]
    loss: number[]
    val_loss?: number[]
    val_accuracy?: number[]
  }>
  aggregated?: Record<string, { mean: number; std: number }>
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
    grid: { left: 80, right: 80, top: 60, bottom: 60, containLabel: false },
    xAxis: { type: 'category', data: data.classes, name: 'Predicted Label', nameLocation: 'middle', nameGap: 30, axisLabel: { fontSize: 12 }, splitArea: { show: true } },
    yAxis: { type: 'category', data: data.classes, name: 'True Label', nameLocation: 'middle', nameGap: 55, axisLabel: { fontSize: 12 }, splitArea: { show: true }, inverse: true },
    visualMap: { min: 0, max: maxValue || 1, calculable: true, orient: 'vertical', right: 10, top: 'center', inRange: { color: ['#e0e7ff', '#3730a3'] }, itemWidth: 15, itemHeight: 120, text: ['High', 'Low'], textGap: 5, textStyle: { fontSize: 10 } },
    series: [{ type: 'heatmap', data: data.data, label: { show: true, fontSize: 14, fontWeight: 'bold' }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } } }]
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'Confusion Matrix'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '420px', width: '100%' }} />
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
    legend: {
      bottom: 0,
      left: 'center',
      type: 'plain',
      width: '90%',
      itemWidth: 15,
      itemHeight: 10,
      itemGap: 10,
      textStyle: { fontSize: 11 }
    },
    grid: { left: 80, right: 40, top: 60, bottom: 110 },
    xAxis: { type: 'value', name: 'False Positive Rate', min: 0, max: 1, nameLocation: 'middle', nameGap: 35 },
    yAxis: { type: 'value', name: 'True Positive Rate', min: 0, max: 1, nameLocation: 'middle', nameGap: 55 },
    series
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'ROC Curve'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '420px', width: '100%' }} />
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
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const epoch = params[0]?.data[0]
        const lines = params.map((p: any) => {
          const value = typeof p.data[1] === 'number' ? p.data[1].toFixed(4) : p.data[1]
          return `<span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${p.color};"></span>${p.seriesName}: ${value}`
        })
        return `Epoch: ${epoch}<br/>${lines.join('<br/>')}`
      }
    },
    legend: {
      bottom: 0,
      left: 'center',
      type: 'plain',
      width: '90%',
      itemWidth: 15,
      itemHeight: 10,
      itemGap: 10,
      textStyle: { fontSize: 11 }
    },
    grid: { left: 80, right: 40, top: 60, bottom: 110 },
    xAxis: { type: 'value', name: 'Epoch', nameLocation: 'middle', nameGap: 35, min: 1 },
    yAxis: { type: 'value', name: 'Loss', nameLocation: 'middle', nameGap: 55 },
    series
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'Loss Curve'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '420px', width: '100%' }} />
    </div>
  )
}

export function KFoldLossCurveChart({ data, title }: { data: KFoldLossCurveData } & ChartProps) {
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'kfold_loss_curve.png', 600), [])

  // Sort fold names for consistent ordering
  const foldNames = Object.keys(data.folds).sort((a, b) => {
    const numA = parseInt(a.replace('fold_', ''))
    const numB = parseInt(b.replace('fold_', ''))
    return numA - numB
  })

  // Create series for each fold
  const series: any[] = foldNames.flatMap((foldName, i) => {
    const fold = data.folds[foldName]
    const foldLabel = `F${parseInt(foldName.replace('fold_', '')) + 1}`
    const result: any[] = [
      {
        name: `${foldLabel} Train`,
        type: 'line',
        data: fold.epochs.map((epoch, j) => [epoch, fold.loss[j]]),
        lineStyle: { width: 2, color: COLORS[i % COLORS.length] },
        itemStyle: { color: COLORS[i % COLORS.length] },
        showSymbol: false,
        smooth: true
      }
    ]
    if (fold.val_loss && fold.val_loss.length > 0) {
      result.push({
        name: `${foldLabel} Val`,
        type: 'line',
        data: fold.epochs.slice(0, fold.val_loss.length).map((epoch, j) => [epoch, fold.val_loss![j]]),
        lineStyle: { width: 2, type: 'dashed', color: COLORS[i % COLORS.length] },
        itemStyle: { color: COLORS[i % COLORS.length] },
        showSymbol: false,
        smooth: true
      })
    }
    return result
  })

  // Calculate legend layout based on number of folds
  const numSeries = series.length
  // Base bottom margin is 110 (keeps ~250px grid height matching others)
  // Only expand for > 6 series (more than 3 folds) to keep alignment for standard cases
  const bottomMargin = numSeries > 6 ? 170 : 110

  const option: EChartsOption = {
    title: { text: title || `K-Fold Training Loss (${data.num_folds} Folds)`, left: 'center', textStyle: { fontSize: 16 }, top: 10 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const epoch = params[0]?.data[0]
        const lines = params.map((p: any) => {
          const value = typeof p.data[1] === 'number' ? p.data[1].toFixed(4) : p.data[1]
          return `<span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${p.color};"></span>${p.seriesName}: ${value}`
        })
        return `Epoch: ${epoch}<br/>${lines.join('<br/>')}`
      }
    },
    legend: {
      bottom: 0,
      left: 'center',
      type: 'plain',
      width: '90%',
      itemWidth: 15,
      itemHeight: 10,
      itemGap: 10,
      textStyle: { fontSize: 10 },
    },
    grid: { left: 80, right: 40, top: 60, bottom: bottomMargin },
    xAxis: { type: 'value', name: 'Epoch', nameLocation: 'middle', nameGap: 35, min: 1 },
    yAxis: { type: 'value', name: 'Loss', nameLocation: 'middle', nameGap: 55 },
    series
  }

  // Adjust chart height based on legend size
  const chartHeight = numSeries > 6 ? '480px' : '420px'

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || `K-Fold Loss Curve (${data.num_folds} Folds)`}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: chartHeight, width: '100%' }} />
    </div>
  )
}

interface KMCurveData {
  high_risk: { times: number[]; probs: number[] }
  low_risk: { times: number[]; probs: number[] }
  cutoff: number
}

export function KMCurveChart({ data, title }: { data: KMCurveData } & ChartProps) {
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'km_curve.png', 600), [])

  // Step line data: convert to [time, prob] pairs for ECharts step-after
  const highRiskData = data.high_risk.times.map((t, i) => [t, data.high_risk.probs[i]])
  const lowRiskData = data.low_risk.times.map((t, i) => [t, data.low_risk.probs[i]])

  const option: EChartsOption = {
    title: { text: title || 'Kaplan-Meier Survival Curve', left: 'center', textStyle: { fontSize: 16 }, top: 10 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const lines = params.map((p: any) => `${p.seriesName}: ${(p.data[1] * 100).toFixed(1)}%`)
        return `Time: ${params[0]?.data[0]?.toFixed(2)}<br/>${lines.join('<br/>')}`
      }
    },
    legend: {
      bottom: 0,
      left: 'center',
      type: 'plain',
      width: '90%',
      itemWidth: 15,
      itemHeight: 10,
      itemGap: 10,
      textStyle: { fontSize: 11 }
    },
    grid: { left: 80, right: 40, top: 60, bottom: 110 },
    xAxis: { type: 'value', name: 'Time', nameLocation: 'middle', nameGap: 35, min: 0 },
    yAxis: { type: 'value', name: 'Survival Probability', nameLocation: 'middle', nameGap: 55, min: 0, max: 1.05 },
    series: [
      {
        name: 'Low Risk (Risk < Median)',
        type: 'line',
        step: 'end',
        data: lowRiskData,
        lineStyle: { width: 2, color: '#10b981' },
        itemStyle: { color: '#10b981' },
        showSymbol: false
      },
      {
        name: 'High Risk (Risk >= Median)',
        type: 'line',
        step: 'end',
        data: highRiskData,
        lineStyle: { width: 2, color: '#ef4444' },
        itemStyle: { color: '#ef4444' },
        showSymbol: false
      }
    ]
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || 'KM Curve'}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title="Export PNG (600 DPI)"><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: '420px', width: '100%' }} />
    </div>
  )
}

export type { ConfusionMatrixData, RocCurveData, LossCurveData, KFoldLossCurveData, KMCurveData }