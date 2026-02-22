import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Box, Database, Tag, Brain, ChevronDown, ChevronUp, Network, Fingerprint, Activity, Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { cn } from '../../lib/utils'

export interface ModelInfo {
  id: string
  name: string
  task_type: string
  data_type: string
  feature_extractor?: string
  embedding_dim?: number
  classes?: string[]
  created_at?: string
  task_id?: string
}

export interface ModelListConfig {
  models: ModelInfo[]
}

/**
 * Parse [MODEL_LIST] block from message content
 */
export function parseModelListConfig(content: string): ModelListConfig | null {
  const match = content.match(/\[MODEL_LIST\]([\s\S]*?)\[\/MODEL_LIST\]/)
  if (!match) return null
  try {
    return JSON.parse(match[1].trim())
  } catch (e) {
    console.error('Failed to parse model list config:', e)
    return null
  }
}

/**
 * Remove [MODEL_LIST] block from content
 */
export function removeModelListBlock(content: string): string {
  return content.replace(/\[MODEL_LIST\]([\s\S]*?)\[\/MODEL_LIST\]/g, '').trim()
}

export function ModelListCard({ config }: { config: ModelListConfig }) {
  const { t } = useTranslation()
  const { models } = config
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id)
  }

  if (!models || models.length === 0) {
    return (
      <Card className="w-full max-w-full border-dashed bg-muted/20">
        <CardContent className="flex flex-col items-center justify-center py-8 text-muted-foreground">
          <Box className="w-10 h-10 mb-2 opacity-20" />
          <p className="text-sm">{t('chatComponents.modelList.noModelsFound')}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="w-full max-w-full space-y-3">
      <div className="flex items-center justify-between px-1">
        <h3 className="text-sm font-medium text-foreground/80 flex items-center gap-2">
          <Brain className="w-4 h-4 text-primary" />
          {t('chatComponents.modelList.title', { count: models.length })}
        </h3>
      </div>

      <div className="grid gap-3 sm:grid-cols-1 md:grid-cols-1 lg:grid-cols-1">
        {models.map((model, index) => (
          <motion.div
            key={model.id || index}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.05 }}
          >
            <Card className={cn(
              "overflow-hidden transition-all duration-200 hover:shadow-md border-l-4",
              model.task_type === 'survival' ? 'border-l-orange-500' : 'border-l-blue-500'
            )}>
              <div 
                className="p-3 sm:p-4 cursor-pointer hover:bg-muted/30 transition-colors"
                onClick={() => toggleExpand(model.id)}
              >
                <div className="flex items-start justify-between gap-2 sm:gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1.5">
                      <h4 className="font-semibold text-sm truncate max-w-[200px] sm:max-w-xs" title={model.name}>
                        {model.name}
                      </h4>
                      <Badge variant="outline" className={cn(
                        "text-[10px] h-5 px-1.5 font-normal shrink-0",
                        model.task_type === 'survival' ? "bg-orange-50 text-orange-700 border-orange-200" : "bg-blue-50 text-blue-700 border-blue-200"
                      )}>
                        {model.task_type === 'survival' ? t('chatComponents.modelList.survival') : t('chatComponents.modelList.classification')}
                      </Badge>
                    </div>
                    
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1">
                        <Database className="w-3 h-3" />
                        <span>{model.data_type === 'wsi' ? 'WSI' : 'Patch'}</span>
                      </div>
                      {model.feature_extractor && (
                        <div className="flex items-center gap-1">
                          <Network className="w-3 h-3" />
                          <span className="truncate max-w-[120px]">{model.feature_extractor}</span>
                        </div>
                      )}
                    </div>
                  </div>
                  
                  <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 text-muted-foreground -mr-1">
                    {expandedId === model.id ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </Button>
                </div>

                <AnimatePresence>
                  {expandedId === model.id && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <div className="pt-3 mt-2 border-t text-sm space-y-3">
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <span className="text-xs text-muted-foreground flex items-center gap-1">
                              <Fingerprint className="w-3 h-3" /> {t('chatComponents.modelList.modelId')}
                            </span>
                            <p className="font-mono text-[10px] sm:text-xs bg-muted/50 p-1.5 rounded break-all select-all">
                              {model.id}
                            </p>
                          </div>
                          
                          {model.task_id && (
                            <div className="space-y-1">
                              <span className="text-xs text-muted-foreground flex items-center gap-1">
                                <Activity className="w-3 h-3" /> {t('chatComponents.modelList.taskId')}
                              </span>
                              <p className="font-mono text-[10px] sm:text-xs bg-muted/50 p-1.5 rounded break-all select-all">
                                {model.task_id}
                              </p>
                            </div>
                          )}
                        </div>

                        {model.classes && model.classes.length > 0 && (
                          <div className="space-y-1.5">
                            <span className="text-xs text-muted-foreground flex items-center gap-1">
                              <Tag className="w-3 h-3" /> {t('chatComponents.modelList.classes', { count: model.classes.length })}
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {model.classes.map((cls, i) => (
                                <Badge key={i} variant="secondary" className="text-[10px] bg-secondary/50 font-normal">
                                  {cls}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground pt-1">
                          {model.embedding_dim && (
                            <div className="bg-muted/30 px-2 py-1 rounded">
                              {t('chatComponents.modelList.embeddingDim')}: <span className="text-foreground font-mono">{model.embedding_dim}</span>
                            </div>
                          )}
                          {model.created_at && (
                            <div className="flex items-center gap-1 bg-muted/30 px-2 py-1 rounded">
                              <Clock className="w-3 h-3" />
                              <span>{new Date(model.created_at).toLocaleDateString()}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
