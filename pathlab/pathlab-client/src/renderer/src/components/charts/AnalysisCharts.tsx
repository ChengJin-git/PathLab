import { useRef, useCallback, useMemo, memo } from 'react'
import { useTranslation } from 'react-i18next'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { Download } from 'lucide-react'

interface ConfusionMatrixData {
  classes: string[]
  data: [number, number, number][] // [predIndex, trueIndex, value]
}

interface RocCurveData {
  classes: string[]
  data: Record<string, {
    fpr: number[]
    tpr: number[]
    auc: number
    // CI data (optional, from bootstrap resampling)
    fpr_grid?: number[]
    tpr_lower?: number[]
    tpr_upper?: number[]
  }>
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



export interface KMCurveData {
  high_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
  low_risk: { times: number[]; probs: number[]; ci_lower?: number[]; ci_upper?: number[] }
  cutoff: number
  c_index?: number
}

interface ChartProps {
  title: string
  compact?: boolean
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

export const ConfusionMatrixChart = memo(function ConfusionMatrixChart({ data, title, compact }: { data: ConfusionMatrixData } & ChartProps) {
  const { t } = useTranslation()
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'confusion_matrix.png', 600), [])

  const option: EChartsOption = useMemo(() => {
    const maxValue = Math.max(...data.data.map(d => d[2]))
    return {
      title: { text: title || t('analysisCharts.confusionMatrix'), left: 'center', textStyle: { fontSize: compact ? 14 : 16 }, top: compact ? 5 : 10 },
      tooltip: {
        position: 'top',
        formatter: (params: any) => {
          const [pred, actual, value] = params.data
          return `${t('analysisCharts.trueLabel')}: ${data.classes[actual]}<br/>${t('analysisCharts.predictedLabel')}: ${data.classes[pred]}<br/>${t('analysisCharts.count')}: ${value}`
        }
      },
      grid: compact
        ? { left: 60, right: 35, top: 40, bottom: 125, containLabel: false }
        : { left: '20%', right: 110, top: 60, bottom: 100, containLabel: false },
      xAxis: {
        type: 'category',
        data: data.classes,
        name: t('analysisCharts.predictedLabel'),
        nameLocation: 'middle',
        nameGap: compact ? 80 : 60,
        nameTextStyle: { fontSize: compact ? 11 : 12 },
        axisLabel: {
          fontSize: compact ? 10 : 12,
          rotate: compact ? 30 : 0,
          interval: 0,
          formatter: (value: string) => {
            const maxLen = compact ? 10 : 12
            if (value.length <= maxLen) return value
            const words = value.split(/[\s-]+/)
            const lines: string[] = []
            let line = ''
            for (const word of words) {
              if ((line + ' ' + word).trim().length <= maxLen) {
                line = (line + ' ' + word).trim()
              } else {
                if (line) lines.push(line)
                line = word
              }
            }
            if (line) lines.push(line)
            return lines.join('\n')
          }
        },
        splitArea: { show: true }
      },
      yAxis: {
        type: 'category',
        data: data.classes,
        name: t('analysisCharts.trueLabel'),
        nameLocation: 'middle',
        nameGap: compact ? 35 : 85,
        nameTextStyle: { fontSize: compact ? 11 : 12 },
        axisLabel: {
          fontSize: compact ? 10 : 12,
          interval: 0,
          formatter: (value: string) => {
            const maxLen = compact ? 10 : 12
            if (value.length <= maxLen) return value
            const words = value.split(/[\s-]+/)
            const lines: string[] = []
            let line = ''
            for (const word of words) {
              if ((line + ' ' + word).trim().length <= maxLen) {
                line = (line + ' ' + word).trim()
              } else {
                if (line) lines.push(line)
                line = word
              }
            }
            if (line) lines.push(line)
            return lines.join('\n')
          }
        },
        splitArea: { show: true },
        inverse: true
      },
      visualMap: {
        min: 0,
        max: maxValue || 1,
        calculable: true,
        orient: compact ? 'horizontal' : 'vertical',
        align: compact ? 'auto' : 'left',
        right: compact ? 'center' : 0,
        top: compact ? 'auto' : 'center',
        bottom: compact ? 30 : 'auto',
        inRange: { color: ['#e0e7ff', '#3730a3'] },
        itemWidth: 15,
        itemHeight: compact ? 100 : 120,
        text: [t('analysisCharts.high'), t('analysisCharts.low')],
        textGap: 5,
        textStyle: { fontSize: 10 }
      },
      series: [{ type: 'heatmap', data: data.data, label: { show: true, fontSize: compact ? 10 : 14, fontWeight: 'bold' }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } } }]
    }
  }, [data, title, compact, t])

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || t('analysisCharts.confusionMatrix')}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title={t('analysisCharts.exportPng')}><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: compact ? '300px' : '420px', width: '100%' }} notMerge={true} />
    </div>
  )
})

export const RocCurveChart = memo(function RocCurveChart({ data, title, compact }: { data: RocCurveData } & ChartProps) {
  const { t } = useTranslation()
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'roc_curve.png', 600), [])

  const option: EChartsOption = useMemo(() => {
    const series: any[] = []
    const legendData: { name: string }[] = []

    const classesWithCI: string[] = []
    data.classes.filter(cls => data.data[cls]).forEach((cls, i) => {
      const clsData = data.data[cls]
      const hasCI = clsData.fpr_grid && clsData.tpr_lower && clsData.tpr_upper

      if (hasCI) {
        classesWithCI.push(cls)
        const color = COLORS[i % COLORS.length]
        const ciData = clsData.fpr_grid!.map((fpr, j) => [fpr, clsData.tpr_lower![j], clsData.tpr_upper![j]])
        series.push({
          name: `${cls} 95% CI`,
          type: 'custom',
          data: ciData,
          z: 1,
          silent: true,
          renderItem: (params: any, api: any) => {
            if (params.dataIndex === 0) {
              const points: number[][] = []
              for (let j = 0; j < ciData.length; j++) {
                const x = api.coord([ciData[j][0], ciData[j][1]])[0]
                const y = api.coord([ciData[j][0], ciData[j][1]])[1]
                points.push([x, y])
              }
              for (let j = ciData.length - 1; j >= 0; j--) {
                const x = api.coord([ciData[j][0], ciData[j][2]])[0]
                const y = api.coord([ciData[j][0], ciData[j][2]])[1]
                points.push([x, y])
              }
              return {
                type: 'polygon',
                shape: { points },
                style: { fill: color, opacity: 0.2 },
                silent: true
              }
            }
            return null
          }
        })
      }
    })

    data.classes.filter(cls => data.data[cls]).forEach((cls, i) => {
      const clsData = data.data[cls]
      series.push({
        name: `${cls} (AUC = ${clsData.auc.toFixed(3)})`,
        type: 'line',
        smooth: true,
        data: clsData.fpr.map((fpr, j) => [fpr, clsData.tpr[j]]),
        lineStyle: { width: 2, color: COLORS[i % COLORS.length] },
        itemStyle: { color: COLORS[i % COLORS.length] },
        showSymbol: false,
        z: 2
      })
      legendData.push({ name: `${cls} (AUC = ${clsData.auc.toFixed(3)})` })
      if (classesWithCI.includes(cls)) {
        legendData.push({ name: `${cls} 95% CI` })
      }
    })

    series.push({ name: 'Random (AUC = 0.5)', type: 'line', data: [[0, 0], [1, 1]], lineStyle: { width: 1, type: 'dashed', color: '#666' }, itemStyle: { color: '#666' }, showSymbol: false, z: 2 })

    return {
      title: { text: title || t('analysisCharts.rocCurve'), left: 'center', textStyle: { fontSize: compact ? 14 : 16 }, top: compact ? 5 : 10 },
      tooltip: {
        trigger: 'axis', formatter: (params: any) => {
          const filtered = params.filter((p: any) => !p.seriesName.includes('CI Lower'))
          const lines = filtered.map((p: any) => `${p.seriesName}: TPR=${p.data[1]?.toFixed(3)}`)
          return `FPR: ${params[0]?.data[0]?.toFixed(3)}<br/>${lines.join('<br/>')}`
        }
      },
      legend: {
        top: compact ? 25 : 35,
        left: 'center',
        type: 'scroll',
        width: '90%',
        itemWidth: 15,
        itemHeight: 10,
        itemGap: 10,
        textStyle: { fontSize: compact ? 10 : 11 },
        formatter: (name: string) => {
          const maxLen = compact ? 20 : 30
          return name.length > maxLen ? name.substring(0, maxLen) + '...' : name
        },
        tooltip: {
          show: true
        },
        data: legendData
      },
      grid: compact
        ? { left: 50, right: 15, top: 60, bottom: 45 }
        : { left: 80, right: 40, top: 70, bottom: 60 },
      xAxis: { type: 'value', name: t('analysisCharts.falsePositiveRate'), min: 0, max: 1, nameLocation: 'middle', nameGap: compact ? 25 : 35, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      yAxis: { type: 'value', name: t('analysisCharts.truePositiveRate'), min: 0, max: 1, nameLocation: 'middle', nameGap: compact ? 40 : 55, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      series
    }
  }, [data, title, compact, t])

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || t('analysisCharts.rocCurve')}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title={t('analysisCharts.exportPng')}><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: compact ? '300px' : '420px', width: '100%' }} notMerge={true} />
    </div>
  )
})

export const LossCurveChart = memo(function LossCurveChart({ data, title, compact }: { data: LossCurveData } & ChartProps) {
  const { t } = useTranslation()
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'loss_curve.png', 600), [])

  const option: EChartsOption = useMemo(() => {
    const series: any[] = [{ name: t('analysisCharts.trainingLoss'), type: 'line', data: data.epochs.map((epoch, i) => [epoch, data.loss[i]]), lineStyle: { width: 2, color: COLORS[0] }, itemStyle: { color: COLORS[0] }, showSymbol: false, smooth: true }]
    if (data.val_loss && data.val_loss.length > 0) {
      series.push({ name: t('analysisCharts.validationLoss'), type: 'line', data: data.epochs.slice(0, data.val_loss.length).map((epoch, i) => [epoch, data.val_loss![i]]), lineStyle: { width: 2, type: 'dashed', color: COLORS[3] }, itemStyle: { color: COLORS[3] }, showSymbol: false, smooth: true })
    }

    return {
      title: { text: title || t('analysisCharts.trainingLossCurve'), left: 'center', textStyle: { fontSize: compact ? 14 : 16 }, top: compact ? 5 : 10 },
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const epoch = params[0]?.data[0]
          const lines = params.map((p: any) => {
            const value = typeof p.data[1] === 'number' ? p.data[1].toFixed(4) : p.data[1]
            return `<span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${p.color};"></span>${p.seriesName}: ${value}`
          })
          return `${t('analysisCharts.epoch')}: ${epoch}<br/>${lines.join('<br/>')}`
        }
      },
      legend: {
        top: compact ? 25 : 35,
        left: 'center',
        type: 'scroll',
        width: '90%',
        itemWidth: 15,
        itemHeight: 10,
        itemGap: 10,
        textStyle: { fontSize: compact ? 10 : 11 },
        formatter: (name: string) => {
          const maxLen = compact ? 20 : 30
          return name.length > maxLen ? name.substring(0, maxLen) + '...' : name
        },
        tooltip: { show: true }
      },
      grid: compact
        ? { left: 50, right: 15, top: 60, bottom: 45 }
        : { left: 80, right: 40, top: 70, bottom: 60 },
      xAxis: { type: 'value', name: t('analysisCharts.epoch'), nameLocation: 'middle', nameGap: compact ? 25 : 35, min: 1, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      yAxis: { type: 'value', name: t('analysisCharts.loss'), nameLocation: 'middle', nameGap: compact ? 40 : 55, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      series
    }
  }, [data, title, compact, t])

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || t('analysisCharts.lossCurve')}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title={t('analysisCharts.exportPng')}><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: compact ? '300px' : '420px', width: '100%' }} notMerge={true} />
    </div>
  )
})

export const KFoldLossCurveChart = memo(function KFoldLossCurveChart({ data, title, compact }: { data: KFoldLossCurveData } & ChartProps) {
  const { t } = useTranslation()
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'kfold_loss_curve.png', 600), [])

  const { option, chartHeight } = useMemo(() => {
    const foldNames = Object.keys(data.folds).sort((a, b) => {
      const numA = parseInt(a.replace('fold_', ''))
      const numB = parseInt(b.replace('fold_', ''))
      return numA - numB
    })

    const series: any[] = foldNames.flatMap((foldName, i) => {
      const fold = data.folds[foldName]
      const foldLabel = `F${parseInt(foldName.replace('fold_', '')) + 1}`
      const result: any[] = [
        {
          name: `${foldLabel} ${t('analysisCharts.train')}`,
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
          name: `${foldLabel} ${t('analysisCharts.val')}`,
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

    const numSeries = series.length
    const bottomMargin = numSeries > 6 ? 170 : 110

    const opt: EChartsOption = {
      title: { text: title || t('analysisCharts.kFoldTrainingLoss', { folds: data.num_folds }), left: 'center', textStyle: { fontSize: compact ? 14 : 16 }, top: compact ? 5 : 10 },
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const epoch = params[0]?.data[0]
          const lines = params.map((p: any) => {
            const value = typeof p.data[1] === 'number' ? p.data[1].toFixed(4) : p.data[1]
            return `<span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${p.color};"></span>${p.seriesName}: ${value}`
          })
          return `${t('analysisCharts.epoch')}: ${epoch}<br/>${lines.join('<br/>')}`
        }
      },
      legend: {
        top: compact ? 25 : 35,
        left: 'center',
        type: 'scroll',
        width: '90%',
        itemWidth: 15,
        itemHeight: 10,
        itemGap: 10,
        textStyle: { fontSize: compact ? 9 : 10 },
        formatter: (name: string) => {
          const maxLen = compact ? 15 : 25
          return name.length > maxLen ? name.substring(0, maxLen) + '...' : name
        },
        tooltip: { show: true }
      },
      grid: compact
        ? { left: 50, right: 15, top: 60, bottom: 45 }
        : { left: 80, right: 40, top: 70, bottom: 60 },
      xAxis: { type: 'value', name: t('analysisCharts.epoch'), nameLocation: 'middle', nameGap: compact ? 25 : 35, min: 1, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      yAxis: { type: 'value', name: t('analysisCharts.loss'), nameLocation: 'middle', nameGap: compact ? 40 : 55, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      series
    }

    const height = compact
      ? (numSeries > 6 ? '360px' : '300px')
      : (numSeries > 6 ? '480px' : '420px')

    return { option: opt, chartHeight: height }
  }, [data, title, compact, t])

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || t('analysisCharts.kFoldLossCurve', { folds: data.num_folds })}</span>
        <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title={t('analysisCharts.exportPng')}><Download className="w-4 h-4" /></button>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: chartHeight, width: '100%' }} notMerge={true} />
    </div>
  )
})

export const KMCurveChart = memo(function KMCurveChart({ data, title, compact }: { data: KMCurveData } & ChartProps) {
  const { t } = useTranslation()
  const chartRef = useRef<ReactECharts | null>(null)
  const handleExport = useCallback(() => exportChartAsPng(chartRef, 'km_curve.png', 600), [])

  const option: EChartsOption = useMemo(() => {
    const highRiskData = data.high_risk.times.map((t, i) => [t, data.high_risk.probs[i]])
    const lowRiskData = data.low_risk.times.map((t, i) => [t, data.low_risk.probs[i]])

    const hasLowRiskCI = data.low_risk.ci_lower && data.low_risk.ci_upper
    const hasHighRiskCI = data.high_risk.ci_lower && data.high_risk.ci_upper

    const series: any[] = []

    const createStepPolygon = (times: number[], ciLower: number[], ciUpper: number[]) => {
      const points: [number, number][] = []
      for (let i = 0; i < times.length; i++) {
        if (i > 0) {
          points.push([times[i], ciUpper[i - 1]])
        }
        points.push([times[i], ciUpper[i]])
      }
      for (let i = times.length - 1; i >= 0; i--) {
        points.push([times[i], ciLower[i]])
        if (i > 0) {
          points.push([times[i], ciLower[i - 1]])
        }
      }
      return points
    }

    if (hasLowRiskCI) {
      const lowRiskPolygon = createStepPolygon(
        data.low_risk.times,
        data.low_risk.ci_lower!,
        data.low_risk.ci_upper!
      )
      series.push({
        name: `${t('analysisCharts.lowRiskGroup')} 95% CI`,
        type: 'custom',
        renderItem: (_params: any, api: any) => {
          const points = lowRiskPolygon.map(([x, y]) => api.coord([x, y]))
          return {
            type: 'polygon',
            shape: { points },
            style: { fill: 'rgba(16, 185, 129, 0.2)' },
            silent: true,
            z: 1
          }
        },
        data: [0],
        silent: true,
        z: 1
      })
    }

    if (hasHighRiskCI) {
      const highRiskPolygon = createStepPolygon(
        data.high_risk.times,
        data.high_risk.ci_lower!,
        data.high_risk.ci_upper!
      )
      series.push({
        name: `${t('analysisCharts.highRiskGroup')} 95% CI`,
        type: 'custom',
        renderItem: (_params: any, api: any) => {
          const points = highRiskPolygon.map(([x, y]) => api.coord([x, y]))
          return {
            type: 'polygon',
            shape: { points },
            style: { fill: 'rgba(239, 68, 68, 0.2)' },
            silent: true,
            z: 1
          }
        },
        data: [0],
        silent: true,
        z: 1
      })
    }

    series.push(
      {
        name: t('analysisCharts.lowRiskGroup'),
        type: 'line',
        step: 'end',
        data: lowRiskData,
        lineStyle: { width: 2, color: '#10b981' },
        itemStyle: { color: '#10b981' },
        showSymbol: false,
        z: 2
      },
      {
        name: t('analysisCharts.highRiskGroup'),
        type: 'line',
        step: 'end',
        data: highRiskData,
        lineStyle: { width: 2, color: '#ef4444' },
        itemStyle: { color: '#ef4444' },
        showSymbol: false,
        z: 2
      }
    )

    return {
      title: { text: title || t('analysisCharts.kmSurvivalCurve'), left: 'center', textStyle: { fontSize: compact ? 14 : 16 }, top: compact ? 5 : 10 },
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const mainLines = params.filter((p: any) =>
            p.seriesName === t('analysisCharts.lowRiskGroup') || p.seriesName === t('analysisCharts.highRiskGroup')
          )
          if (mainLines.length === 0) return ''
          const lines = mainLines.map((p: any) => `${p.seriesName}: ${(p.data[1] * 100).toFixed(1)}%`)
          return `${t('analysisCharts.time')}: ${mainLines[0]?.data[0]?.toFixed(2)}<br/>${lines.join('<br/>')}`
        }
      },
      legend: {
        bottom: 5,
        left: 'center',
        type: 'scroll',
        orient: 'horizontal',
        itemWidth: 20,
        itemHeight: 10,
        itemGap: 15,
        textStyle: { fontSize: compact ? 10 : 11 },
        formatter: (name: string) => {
          const maxLen = compact ? 20 : 30
          return name.length > maxLen ? name.substring(0, maxLen) + '...' : name
        },
        tooltip: { show: true },
        data: [
          { name: t('analysisCharts.lowRiskGroup') },
          { name: t('analysisCharts.highRiskGroup') },
          ...(hasLowRiskCI ? [{ name: `${t('analysisCharts.lowRiskGroup')} 95% CI` }] : []),
          ...(hasHighRiskCI ? [{ name: `${t('analysisCharts.highRiskGroup')} 95% CI` }] : [])
        ],
        width: compact ? 300 : 380
      },
      grid: compact
        ? { left: 50, right: 15, top: 40, bottom: 125 }
        : { left: 80, right: 40, top: 60, bottom: 80 },
      xAxis: { type: 'value', name: t('analysisCharts.time'), nameLocation: 'middle', nameGap: compact ? 25 : 35, min: 0, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      yAxis: { type: 'value', name: t('analysisCharts.survivalProbability'), nameLocation: 'middle', nameGap: compact ? 40 : 55, min: 0, max: 1.05, nameTextStyle: { fontSize: compact ? 10 : 12 }, axisLabel: { fontSize: compact ? 10 : 12 } },
      series
    }
  }, [data, title, compact, t])

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="p-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{title || t('analysisCharts.survivalCurve')}</span>
        <div className="flex items-center gap-2">
          {data.c_index !== undefined && (
            <span className="text-xs font-semibold px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">
              C-Idx: {data.c_index.toFixed(3)}
            </span>
          )}
          <button onClick={handleExport} className="text-indigo-600 hover:text-indigo-800" title={t('analysisCharts.exportPng')}><Download className="w-4 h-4" /></button>
        </div>
      </div>
      <ReactECharts ref={chartRef} option={option} style={{ height: compact ? '300px' : '420px', width: '100%' }} notMerge={true} />
    </div>
  )
})

export type { ConfusionMatrixData, RocCurveData, LossCurveData, KFoldLossCurveData }
