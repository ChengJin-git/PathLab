import { useState, useMemo } from 'react'
import { X } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import type { EmailTemplatesConfig } from '../../api/settings'

interface EmailTemplateModalProps {
  templates: EmailTemplatesConfig
  onSave: (next: EmailTemplatesConfig) => Promise<void>
  onClose: () => void
}

type TemplateKey = keyof EmailTemplatesConfig

const TEMPLATE_META: Array<{ key: TemplateKey; label: string }> = [
  { key: 'new_user_registration_notice', label: '新用户注册通知（用户）' },
  { key: 'account_activated', label: '账号激活通知（用户）' },
  { key: 'task_completed_notice', label: '任务完成通知（用户）' },
  { key: 'admin_new_user_registration_notice', label: '新用户注册通知（管理员）' }
]

export function EmailTemplateModal({ templates, onSave, onClose }: EmailTemplateModalProps) {
  const [activeKey, setActiveKey] = useState<TemplateKey>('new_user_registration_notice')
  const [draft, setDraft] = useState<EmailTemplatesConfig>(templates)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const current = useMemo(() => draft[activeKey], [draft, activeKey])

  const updateCurrent = (patch: Partial<{ subject: string; html: string }>) => {
    setDraft(prev => ({
      ...prev,
      [activeKey]: {
        ...prev[activeKey],
        ...patch
      }
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await onSave(draft)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save templates')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="w-full max-w-5xl bg-white rounded-xl border shadow-2xl overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">邮件模板配置</h3>
            <p className="text-sm text-gray-600 mt-1">可用变量示例：{'{display_name}'}, {'{username}'}, {'{task_id}'}, {'{task_status}'}, {'{registration_email}'}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] min-h-[520px]">
          <div className="border-r bg-gray-50 p-3 space-y-2">
            {TEMPLATE_META.map(item => (
              <button
                key={item.key}
                type="button"
                onClick={() => setActiveKey(item.key)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition ${
                  activeKey === item.key
                    ? 'bg-primary-100 text-primary-900 border border-primary-200'
                    : 'hover:bg-gray-100 text-gray-700 border border-transparent'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="p-5 space-y-4">
            <div className="space-y-2">
              <label htmlFor="email-template-subject" className="text-xs uppercase tracking-wide font-semibold text-gray-700">Subject</label>
              <Input
                id="email-template-subject"
                value={current.subject}
                onChange={(e) => updateCurrent({ subject: e.target.value })}
                placeholder="Email subject"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="email-template-html" className="text-xs uppercase tracking-wide font-semibold text-gray-700">HTML</label>
              <textarea
                id="email-template-html"
                className="w-full h-[320px] border rounded-md px-3 py-2 text-sm font-mono"
                value={current.html}
                onChange={(e) => updateCurrent({ html: e.target.value })}
                placeholder="<div>...</div>"
              />
            </div>

            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{error}</div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose} disabled={saving}>取消</Button>
              <Button onClick={handleSave} disabled={saving}>保存模板</Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
