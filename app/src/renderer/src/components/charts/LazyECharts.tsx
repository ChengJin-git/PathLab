import { forwardRef, lazy, Suspense } from 'react'
import type EChartsReact from 'echarts-for-react'
import type { EChartsReactProps } from 'echarts-for-react'

const Chart = lazy(() => import('echarts-for-react'))
const LazyECharts = forwardRef<EChartsReact, EChartsReactProps>((props, ref) => (
  <Suspense fallback={<div aria-busy="true" style={props.style} className="rounded-lg bg-slate-50" />}>
    <Chart ref={ref} {...props} />
  </Suspense>
))
LazyECharts.displayName = 'LazyECharts'
export default LazyECharts
