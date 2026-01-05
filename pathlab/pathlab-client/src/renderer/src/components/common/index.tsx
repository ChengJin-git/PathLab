import React from 'react'
import { PageHeader as OriginalPageHeader } from '../PageHeader'
import { Card as UiCard, CardHeader, CardTitle, CardContent } from '../ui/card'
import { Button as UiButton } from '../ui/button'
import { LucideIcon, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

// PageHeader wrapper
export const PageHeader = ({ title, description, actions, children }: { title: string, description?: string, actions?: React.ReactNode, children?: React.ReactNode }) => {
  return (
    <OriginalPageHeader title={title} description={description}>
      {actions}
      {children}
    </OriginalPageHeader>
  )
}

// Card wrapper
interface CardProps {
  title?: string
  description?: string
  icon?: LucideIcon
  iconColor?: string
  headerAction?: React.ReactNode
  children: React.ReactNode
  className?: string
  noPadding?: boolean
}

export const Card = ({ title, description, icon: Icon, iconColor, headerAction, children, className, noPadding }: CardProps) => {
  return (
    <UiCard className={className}>
      {(title || Icon || headerAction) && (
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            {Icon && <Icon className={cn("w-5 h-5", iconColor || 'text-gray-500')} />}
            <div className="flex flex-col">
                {title && <CardTitle className="text-lg font-semibold">{title}</CardTitle>}
                {description && <p className="text-sm text-gray-500">{description}</p>}
            </div>
          </div>
          {headerAction && <div>{headerAction}</div>}
        </CardHeader>
      )}
      <CardContent className={noPadding ? 'p-0' : ''}>
        {children}
      </CardContent>
    </UiCard>
  )
}

// Button wrapper
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: LucideIcon
  loading?: boolean
  children?: React.ReactNode
}

export const Button = ({ variant = 'primary', size = 'md', icon: Icon, loading, children, className, ...props }: ButtonProps) => {
  const variantMap: Record<string, "default" | "destructive" | "outline" | "secondary" | "ghost" | "link"> = {
    primary: 'default',
    secondary: 'secondary',
    outline: 'outline',
    ghost: 'ghost',
    danger: 'destructive'
  }
  
  const sizeMap: Record<string, "default" | "sm" | "lg" | "icon"> = {
    sm: 'sm',
    md: 'default',
    lg: 'lg'
  }

  return (
    <UiButton 
      variant={variantMap[variant] || 'default'} 
      size={sizeMap[size] || 'default'} 
      className={className}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      ) : Icon ? (
        <Icon className={cn("h-4 w-4", children ? "mr-2" : "")} />
      ) : null}
      {children}
    </UiButton>
  )
}
