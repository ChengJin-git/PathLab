import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPublicSettings } from '../../api/settings'

let contactRequest: Promise<string> | null = null

function loadContact(): Promise<string> {
  contactRequest ??= getPublicSettings()
    .then((settings) => settings.contact_email?.trim() || '')
    .catch(() => {
      contactRequest = null
      return ''
    })
  return contactRequest
}

/** Contact address configured by the operator (PATHLAB_CONTACT_EMAIL), or a neutral fallback. */
export function InstallationContact({ className }: { className?: string }) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  useEffect(() => {
    let active = true
    void loadContact().then((value) => { if (active) setEmail(value) })
    return () => { active = false }
  }, [])
  if (!email) return <span className={className}>{t('common.installationAdministrator')}</span>
  return <a href={`mailto:${email}`} className={className}>{email}</a>
}
