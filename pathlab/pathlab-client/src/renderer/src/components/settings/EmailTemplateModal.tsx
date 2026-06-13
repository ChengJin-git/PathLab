import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { X } from 'lucide-react'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import { Input } from '../ui/input'
import type { EmailTemplatesConfig } from '../../api/settings'
import { ModalShell } from '../ui/modal-shell'

type EditorMode = 'visual' | 'source' | 'preview'

const LOGO_PLACEHOLDER = '{logo_html}'
const LOGO_PREVIEW_HTML =
  '<span data-tpl="logo_html" contenteditable="false" style="display:block;pointer-events:none;">' +
  '<img src="/images/pathlab-logo.png" alt="PathLab" style="height:40px;width:auto;margin-bottom:24px;display:block;" />' +
  '</span>'

function injectLogoPreview(html: string): string {
  return html.replaceAll(LOGO_PLACEHOLDER, LOGO_PREVIEW_HTML)
}

function stripLogoPreview(html: string): string {
  return html.replace(/<span[^>]*data-tpl="logo_html"[^>]*>[\s\S]*?<\/span>/gi, LOGO_PLACEHOLDER)
}

const LEGAL_FOOTER_HTML =
  "<hr style='border:none;border-top:1px solid #e0e0e0;margin:32px 0 16px'>" +
  "<p style='font-size:11px;color:#999;line-height:1.6;font-family:Arial,sans-serif;'>" +
  "This message contains confidential information intended for a specific individual " +
  "and purpose. If you are not the intended recipient, you should delete this message " +
  "and notify the sender, " +
  "<a href='https://smartlab.cse.ust.hk/' style='color:#999;'>SmartLab</a>, " +
  "and The Hong Kong University of Science and Technology (the University) immediately. " +
  "Any disclosure, copying, or distribution of this message, or the taking of any action " +
  "based on it, is strictly prohibited and may be unlawful.<br><br>" +
  "SmartLab and the University specifically deny any responsibility for the accuracy or " +
  "quality of information obtained through University E-mail Facilities. Any views and " +
  "opinions expressed are only those of the author(s) and do not necessarily represent " +
  "those of SmartLab or the University, and neither SmartLab nor the University accepts " +
  "liability whatsoever for any losses or damages incurred or caused to any party as a " +
  "result of the use of such information." +
  "</p>"

const TOOLBAR: Array<{ cmd: string; label: string; title: string }> = [
  { cmd: 'bold', label: 'B', title: '粗体' },
  { cmd: 'italic', label: 'I', title: '斜体' },
  { cmd: 'underline', label: 'U', title: '下划线' },
]

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
  const [editorMode, setEditorMode] = useState<EditorMode>('visual')
  const editorRef = useRef<HTMLDivElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)

  const activeKeyRef = useRef(activeKey)
  activeKeyRef.current = activeKey
  const draftRef = useRef(draft)
  draftRef.current = draft
  const editorModeRef = useRef(editorMode)
  editorModeRef.current = editorMode

  const current = useMemo(() => draft[activeKey], [draft, activeKey])

  const flushVisual = useCallback(() => {
    if (editorRef.current) {
      const html = stripLogoPreview(editorRef.current.innerHTML)
      setDraft(prev => ({ ...prev, [activeKeyRef.current]: { ...prev[activeKeyRef.current], html } }))
    }
  }, [])

  const syncEditorContent = useCallback((key: TemplateKey, mode: EditorMode) => {
    if (mode === 'visual' && editorRef.current) {
      editorRef.current.innerHTML = injectLogoPreview(draftRef.current[key].html)
    }
  }, [])

  useEffect(() => { syncEditorContent(activeKey, editorModeRef.current) }, [activeKey, syncEditorContent])
  useEffect(() => { syncEditorContent(activeKeyRef.current, editorMode) }, [editorMode, syncEditorContent])

  useEffect(() => {
    if (previewRef.current) {
      previewRef.current.innerHTML = injectLogoPreview(current.html) + LEGAL_FOOTER_HTML
    }
  }, [current.html])

  const switchMode = (next: EditorMode) => {
    if (editorMode === 'visual') flushVisual()
    setEditorMode(next)
  }

  const switchTemplate = (key: TemplateKey) => {
    if (editorMode === 'visual') flushVisual()
    setActiveKey(key)
  }

  const updateSubject = (subject: string) =>
    setDraft(prev => ({ ...prev, [activeKey]: { ...prev[activeKey], subject } }))

  const updateHtml = (html: string) =>
    setDraft(prev => ({ ...prev, [activeKey]: { ...prev[activeKey], html } }))

  const execFormat = (cmd: string, value?: string) => {
    document.execCommand(cmd, false, value)
    editorRef.current?.focus()
  }

  const handleSave = async () => {
    const html =
      editorMode === 'visual' && editorRef.current
        ? stripLogoPreview(editorRef.current.innerHTML)
        : current.html
    const finalDraft: EmailTemplatesConfig = {
      ...draft,
      [activeKey]: { ...draft[activeKey], html },
    }
    setSaving(true)
    setError(null)
    try {
      await onSave(finalDraft)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save templates')
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell isOpen={true} onClose={onClose} maxWidth="xl" className="max-w-5xl">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">邮件模板配置</h3>
            <p className="text-sm text-gray-500 mt-0.5">
              变量：
              {['{display_name}', '{username}', '{task_id}', '{registration_email}'].map(v => (
                <code key={v} className="bg-gray-100 px-1 rounded text-xs mx-0.5">{v}</code>
              ))}
            </p>
          </div>
          <Button variant="ghost" size="sm" type="button" onClick={onClose} className="h-8 w-8 p-0">
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] min-h-[560px]">
          <div className="border-r bg-gray-50 p-3 space-y-1.5">
            {TEMPLATE_META.map(item => (
              <button
                key={item.key}
                type="button"
                onClick={() => switchTemplate(item.key)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition ${
                  activeKey === item.key
                    ? 'bg-violet-100 text-violet-900 border border-violet-200'
                    : 'hover:bg-gray-100 text-gray-700 border border-transparent'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="p-5 flex flex-col gap-4">
            <div className="space-y-1.5">
              <label htmlFor="tpl-subject" className="text-xs uppercase tracking-wide font-semibold text-gray-700">
                主题
              </label>
              <Input
                id="tpl-subject"
                value={current.subject}
                onChange={(e) => updateSubject(e.target.value)}
                placeholder="Email subject"
              />
            </div>

            <div className="flex-1 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase tracking-wide font-semibold text-gray-700">正文</span>
                <div className="flex rounded-md border overflow-hidden text-xs">
                  {(['visual', 'source', 'preview'] as EditorMode[]).map(m => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => switchMode(m)}
                      className={`px-3 py-1 transition ${
                        editorMode === m
                          ? 'bg-violet-600 text-white'
                          : 'bg-white text-gray-600 hover:bg-gray-50'
                      }`}
                    >
                      {m === 'visual' ? '编辑' : m === 'source' ? 'HTML' : '预览'}
                    </button>
                  ))}
                </div>
              </div>

              {editorMode === 'visual' && (
                <div className="flex items-center gap-0.5 px-2 py-1 bg-gray-50 border border-b-0 rounded-t-md">
                  {TOOLBAR.map(a => (
                    <Tooltip key={a.cmd} content={a.title}>
                      <button
                        type="button"
                        onMouseDown={(e) => { e.preventDefault(); execFormat(a.cmd) }}
                        className="w-7 h-7 flex items-center justify-center rounded text-sm font-medium hover:bg-gray-200 transition text-gray-700"
                      >
                        {a.label}
                      </button>
                    </Tooltip>
                  ))}
                  <div className="w-px h-4 bg-gray-300 mx-1" />
                  <Tooltip content="插入链接">
                    <button
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        const url = window.prompt('链接地址')
                        if (url) execFormat('createLink', url)
                      }}
                      className="px-2 h-7 flex items-center justify-center rounded text-xs hover:bg-gray-200 transition text-gray-600"
                    >
                      链接
                    </button>
                  </Tooltip>
                  <Tooltip content="清除格式">
                    <button
                      type="button"
                      onMouseDown={(e) => { e.preventDefault(); execFormat('removeFormat') }}
                      className="px-2 h-7 flex items-center justify-center rounded text-xs hover:bg-gray-200 transition text-gray-500"
                    >
                      清除格式
                    </button>
                  </Tooltip>
                </div>
              )}

              {editorMode === 'visual' && (
                <div
                  ref={editorRef}
                  contentEditable
                  suppressContentEditableWarning
                  className="flex-1 min-h-[280px] border rounded-b-md px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-violet-400 overflow-auto"
                  style={{ lineHeight: 1.75 }}
                />
              )}

              {editorMode === 'source' && (
                <textarea
                  className="flex-1 min-h-[300px] border rounded-md px-3 py-2 text-sm font-mono resize-none"
                  value={current.html}
                  onChange={(e) => updateHtml(e.target.value)}
                  placeholder="<div>...</div>"
                />
              )}

              <div
                ref={previewRef}
                className={`flex-1 min-h-[300px] border rounded-md px-4 py-3 bg-gray-50 overflow-auto text-sm${editorMode !== 'preview' ? ' hidden' : ''}`}
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{error}</p>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" type="button" onClick={onClose} disabled={saving}>取消</Button>
              <Button type="button" onClick={handleSave} disabled={saving}>
                {saving ? '保存中…' : '保存模板'}
              </Button>
            </div>
          </div>
        </div>
    </ModalShell>
  )
}
