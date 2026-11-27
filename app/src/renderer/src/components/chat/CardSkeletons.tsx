import React from 'react'
import { motion } from 'framer-motion'
import { cn } from '../../lib/utils/utils'

// Animation variants for smooth entry/exit
export const cardTransition = {
    initial: { opacity: 0, scale: 0.95, y: 10 },
    animate: { opacity: 1, scale: 1, y: 0 },
    exit: { opacity: 0, scale: 0.95, transition: { duration: 0.2 } },
    transition: { type: 'spring' as const, stiffness: 300, damping: 30 }
}

interface SkeletonProps {
    className?: string
}

// Base container for skeletons to match Card styling
function SkeletonContainer({ children, className }: { children: React.ReactNode; className?: string }) {
    return (
        <div className={cn("bg-gray-50 border border-gray-200 rounded-2xl p-4 overflow-hidden", className)}>
            <div className="animate-pulse space-y-4">
                {children}
            </div>
        </div>
    )
}

export function ModelListSkeleton() {
    return (
        <div className="mt-3 w-full max-w-full space-y-2">
            {/* Section header */}
            <div className="flex items-center gap-1.5 px-0.5 animate-pulse">
                <div className="w-3.5 h-3.5 rounded-full bg-gray-200" />
                <div className="w-28 h-3.5 rounded bg-gray-200" />
            </div>

            <div className="flex flex-col gap-2">
                {[1, 2].map((i) => (
                    <div key={i} className="rounded-xl border border-gray-100 border-l-[3px] border-l-gray-200 bg-white shadow-sm overflow-hidden animate-pulse">
                        {/* Header */}
                        <div className="px-3 pt-3 pb-2">
                            <div className="flex items-center gap-2">
                                <div className="h-4 w-36 rounded bg-gray-200" />
                                <div className="h-4 w-16 rounded-full bg-gray-100" />
                            </div>
                            <div className="flex items-center gap-1.5 mt-1.5">
                                <div className="h-[22px] w-12 rounded bg-gray-100" />
                                <div className="h-[22px] w-20 rounded bg-gray-100" />
                            </div>
                        </div>

                        {/* IDs */}
                        <div className="px-3 pb-2 grid grid-cols-2 gap-x-3">
                            <div>
                                <div className="h-2.5 w-14 rounded bg-gray-100 mb-1" />
                                <div className="h-5 rounded bg-gray-100" />
                            </div>
                            <div>
                                <div className="h-2.5 w-14 rounded bg-gray-100 mb-1" />
                                <div className="h-5 rounded bg-gray-100" />
                            </div>
                        </div>

                        {/* Classes */}
                        <div className="px-3 pb-2.5 flex gap-1.5">
                            <div className="h-4 w-3 rounded bg-gray-100" />
                            <div className="h-4 w-16 rounded-full bg-gray-100" />
                            <div className="h-4 w-14 rounded-full bg-gray-100" />
                        </div>

                        {/* Action bar */}
                        <div className="border-t border-gray-100 grid grid-cols-3 divide-x divide-gray-100">
                            <div className="h-8 bg-gray-50/80" />
                            <div className="h-8 bg-gray-50/80" />
                            <div className="h-8 bg-gray-50/80" />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

export function GenericCardSkeleton({ className }: SkeletonProps) {
    return (
        <SkeletonContainer className={className}>
            <div className="flex items-center gap-3 mb-4">
                <div className="w-8 h-8 rounded-lg bg-gray-200" />
                <div className="h-4 bg-gray-200 rounded w-1/3" />
            </div>
            <div className="space-y-2">
                <div className="h-4 bg-gray-200 rounded w-full" />
                <div className="h-4 bg-gray-200 rounded w-5/6" />
                <div className="h-4 bg-gray-200 rounded w-4/5" />
            </div>
        </SkeletonContainer>
    )
}

export function OptionButtonsSkeleton() {
    return (
        <div className="flex flex-wrap gap-2 mt-3 animate-pulse">
            {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 w-24 bg-gray-100 rounded-xl border border-gray-200" />
            ))}
        </div>
    )
}

export function TaskConfigSkeleton() {
    return (
        <SkeletonContainer>
            {/* Header */}
            <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
                <div className="w-5 h-5 rounded bg-gray-200" />
                <div className="h-5 bg-gray-200 rounded w-48" />
            </div>

            {/* Form Fields */}
            <div className="space-y-4 pt-2">
                {/* Task Name */}
                <div>
                    <div className="h-3 bg-gray-200 rounded w-20 mb-2" />
                    <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                </div>

                {/* Two cols */}
                <div className="grid grid-cols-2 gap-4">
                    <div>
                        <div className="h-3 bg-gray-200 rounded w-16 mb-2" />
                        <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                    </div>
                    <div>
                        <div className="h-3 bg-gray-200 rounded w-16 mb-2" />
                        <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                    </div>
                </div>

                {/* Dataset */}
                <div>
                    <div className="h-3 bg-gray-200 rounded w-24 mb-2" />
                    <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                </div>

                {/* Split Strategy */}
                <div className="bg-white border border-gray-100 rounded-lg p-3 h-24" />
            </div>
        </SkeletonContainer>
    )
}

export function AnalysisConfigSkeleton() {
    return (
        <SkeletonContainer>
            {/* Header */}
            <div className="flex items-center gap-3 pb-3 border-b border-gray-100">
                <div className="w-5 h-5 rounded bg-gray-200" />
                <div className="h-5 bg-gray-200 rounded w-40" />
            </div>

            {/* Form Fields */}
            <div className="space-y-4 pt-2">
                {/* Model Selection */}
                <div>
                    <div className="h-3 bg-gray-200 rounded w-20 mb-2" />
                    <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                </div>

                {/* Dataset */}
                <div>
                    <div className="h-3 bg-gray-200 rounded w-24 mb-2" />
                    <div className="h-10 bg-white border border-gray-100 rounded-lg" />
                </div>

                {/* Button */}
                <div className="h-10 bg-blue-50 rounded-lg w-full mt-2" />
            </div>
        </SkeletonContainer>
    )
}

export function ChartSkeleton() {
    return (
        <SkeletonContainer>
            <div className="flex items-center justify-between mb-4">
                <div className="h-5 bg-gray-200 rounded w-1/3" />
                <div className="h-8 w-24 bg-gray-200 rounded-lg" />
            </div>
            <div className="h-64 bg-white border border-gray-100 rounded-xl flex items-end justify-around p-4 gap-2">
                <div className="w-full bg-gray-100 rounded-t h-1/3" />
                <div className="w-full bg-gray-100 rounded-t h-1/2" />
                <div className="w-full bg-gray-100 rounded-t h-2/3" />
                <div className="w-full bg-gray-100 rounded-t h-1/4" />
                <div className="w-full bg-gray-100 rounded-t h-3/4" />
            </div>
        </SkeletonContainer>
    )
}

export function MetricSkeleton() {
    return (
        <SkeletonContainer>
            <div className="grid grid-cols-2 gap-4">
                <div className="bg-white p-4 rounded-xl border border-gray-100 h-24" />
                <div className="bg-white p-4 rounded-xl border border-gray-100 h-24" />
                <div className="bg-white p-4 rounded-xl border border-gray-100 h-24" />
                <div className="bg-white p-4 rounded-xl border border-gray-100 h-24" />
            </div>
        </SkeletonContainer>
    )
}

export function ImageRecommendationSkeleton() {
    return (
        <SkeletonContainer>
            <div className="h-5 bg-gray-200 rounded w-1/2 mb-4" />
            <div className="grid grid-cols-3 gap-2">
                <div className="aspect-square bg-gray-200 rounded-lg" />
                <div className="aspect-square bg-gray-200 rounded-lg" />
                <div className="aspect-square bg-gray-200 rounded-lg" />
            </div>
        </SkeletonContainer>
    )
}

export function CSVActionSkeleton() {
    return (
        <SkeletonContainer>
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-gray-200 rounded-lg" />
                <div className="space-y-2 flex-1">
                    <div className="h-4 bg-gray-200 rounded w-1/2" />
                    <div className="h-3 bg-gray-200 rounded w-3/4" />
                </div>
            </div>
        </SkeletonContainer>
    )
}

export function QuickAnalysisViewerSkeleton() {
    return (
        <div className="space-y-4">
            <MetricSkeleton />
            <ChartSkeleton />
        </div>
    )
}
