import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
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
  "<a href='https://smartx.ust.hk/' style='color:#999;'>SmartXLab</a>, " +
  "and The Hong Kong University of Science and Technology (the University) immediately. " +
  "Any disclosure, copying, or distribution of this message, or the taking of any action " +
  "based on it, is strictly prohibited and may be unlawful.<br><br>" +
  "SmartXLab and the University specifically deny any responsibility for the accuracy or " +
  "quality of information obtained through University E-mail Facilities. Any views and " +
  "opinions expressed are only those of the author(s) and do not necessarily represent " +
  "those of SmartXLab or the University, and neither SmartXLab nor the University accepts " +
  "liability whatsoever for any losses or damages incurred or caused to any party as a " +
  "result of the use of such information." +
  "</p>"

const TOOLBAR_CMDS: Array<{ cmd: string; label: string; titleKey: string }> = [
  { cmd: 'bold', label: 'B', titleKey: 'bold' },
  { cmd: 'italic', label: 'I', titleKey: 'italic' },
  { cmd: 'underline', label: 'U', titleKey: 'underline' },
]

interface EmailTemplateModalProps {
  templates: EmailTemplatesConfig
  onSave: (next: EmailTemplatesConfig) => Promise<void>
  onClose: () => void
}

type TemplateKey = keyof EmailTemplatesConfig

const TEMPLATE_KEYS: TemplateKey[] = [
  'new_user_registration_notice',
  'account_activated',
  'task_completed_notice',
  'admin_new_user_registration_notice',
]

export function EmailTemplateModal({ templates, onSave, onClose }: EmailTemplateModalProps) {
  const { t } = useTranslation()
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
        <div className="px-5 py-4 border-b">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-900">{t('settings.emailTemplateModal.title')}</h3>
            <Button variant="ghost" size="sm" type="button" onClick={onClose} className="h-8 w-8 p-0">
              <X className="w-4 h-4" />
            </Button>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            {t('settings.emailTemplateModal.variables')}
            {['{display_name}', '{username}', '{task_id}', '{registration_email}'].map(v => (
              <code key={v} className="bg-gray-100 px-1 rounded text-xs mx-0.5">{v}</code>
            ))}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] min-h-[560px]">
          <div className="border-r bg-gray-50 p-3 space-y-1.5">
            {TEMPLATE_KEYS.map(key => (
              <button
                key={key}
                type="button"
                onClick={() => switchTemplate(key)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition ${
                  activeKey === key
                    ? 'bg-violet-100 text-violet-900 border border-violet-200'
                    : 'hover:bg-gray-100 text-gray-700 border border-transparent'
                }`}
              >
                {t(`settings.emailTemplateModal.templates.${key}`)}
              </button>
            ))}
          </div>

          <div className="p-5 flex flex-col gap-4">
            <div className="space-y-1.5">
              <label htmlFor="tpl-subject" className="text-xs uppercase tracking-wide font-semibold text-gray-700">
                {t('settings.emailTemplateModal.subject')}
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
                <span className="text-xs uppercase tracking-wide font-semibold text-gray-700">{t('settings.emailTemplateModal.body')}</span>
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
                      {m === 'visual' ? t('settings.emailTemplateModal.modeVisual') : m === 'source' ? 'HTML' : t('settings.emailTemplateModal.modePreview')}
                    </button>
                  ))}
                </div>
              </div>

              {editorMode === 'visual' && (
                <div className="flex items-center gap-0.5 px-2 py-1 bg-gray-50 border border-b-0 rounded-t-md">
                  {TOOLBAR_CMDS.map(a => (
                    <Tooltip key={a.cmd} content={t(`settings.emailTemplateModal.${a.titleKey}`)}>
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
                  <Tooltip content={t('settings.emailTemplateModal.insertLink')}>
                    <button
                      type="button"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        const url = window.prompt(t('settings.emailTemplateModal.linkPrompt'))
                        if (url) execFormat('createLink', url)
                      }}
                      className="px-2 h-7 flex items-center justify-center rounded text-xs hover:bg-gray-200 transition text-gray-600"
                    >
                      {t('settings.emailTemplateModal.link')}
                    </button>
                  </Tooltip>
                  <Tooltip content={t('settings.emailTemplateModal.clearFormat')}>
                    <button
                      type="button"
                      onMouseDown={(e) => { e.preventDefault(); execFormat('removeFormat') }}
                      className="px-2 h-7 flex items-center justify-center rounded text-xs hover:bg-gray-200 transition text-gray-500"
                    >
                      {t('settings.emailTemplateModal.clearFormat')}
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
              <Button variant="outline" type="button" onClick={onClose} disabled={saving}>{t('settings.emailTemplateModal.cancel')}</Button>
              <Button type="button" onClick={handleSave} disabled={saving}>
                {saving ? t('settings.emailTemplateModal.saving') : t('settings.emailTemplateModal.save')}
              </Button>
            </div>
          </div>
        </div>
    </ModalShell>
  )
}
