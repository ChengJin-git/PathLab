import { ExternalLink } from 'lucide-react'
import { ReactNode } from 'react'

type SupportedLegalLanguage = 'en-US' | 'zh-CN' | 'zh-HK'
type LegalLinkKey = 'cap486' | 'cap553' | 'cap71' | 'cap457' | 'cap458'

const LEGAL_URLS: Record<SupportedLegalLanguage, Record<LegalLinkKey, string>> = {
  'en-US': {
    cap486: 'https://www.elegislation.gov.hk/hk/cap486?_lang=en',
    cap553: 'https://www.elegislation.gov.hk/hk/cap553?_lang=en',
    cap71: 'https://www.elegislation.gov.hk/hk/cap71?_lang=en',
    cap457: 'https://www.elegislation.gov.hk/hk/cap457?_lang=en',
    cap458: 'https://www.elegislation.gov.hk/hk/cap458?_lang=en',
  },
  'zh-CN': {
    cap486: 'https://www.elegislation.gov.hk/hk/cap486?_lang=sc',
    cap553: 'https://www.elegislation.gov.hk/hk/cap553?_lang=sc',
    cap71: 'https://www.elegislation.gov.hk/hk/cap71?_lang=sc',
    cap457: 'https://www.elegislation.gov.hk/hk/cap457?_lang=sc',
    cap458: 'https://www.elegislation.gov.hk/hk/cap458?_lang=sc',
  },
  'zh-HK': {
    cap486: 'https://www.elegislation.gov.hk/hk/cap486?_lang=zh-Hant-HK',
    cap553: 'https://www.elegislation.gov.hk/hk/cap553?_lang=zh-Hant-HK',
    cap71: 'https://www.elegislation.gov.hk/hk/cap71?_lang=zh-Hant-HK',
    cap457: 'https://www.elegislation.gov.hk/hk/cap457?_lang=zh-Hant-HK',
    cap458: 'https://www.elegislation.gov.hk/hk/cap458?_lang=zh-Hant-HK',
  },
}

function resolveLanguage(language: string): SupportedLegalLanguage {
  if (language === 'zh-CN' || language === 'zh-HK') return language
  return 'en-US'
}

export function LegalInlineLink({ href, children }: { href: string; children?: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-0.5 rounded-sm px-0.5 font-medium text-blue-700 underline decoration-blue-300 underline-offset-2 transition-all hover:bg-blue-50 hover:text-blue-900 hover:decoration-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
    >
      <span>{children}</span>
      <ExternalLink className="w-3 h-3 opacity-75" />
    </a>
  )
}

export function getLegalInlineComponents(language: string) {
  const urls = LEGAL_URLS[resolveLanguage(language)]

  return {
    lawCap486: <LegalInlineLink href={urls.cap486} />,
    lawCap553: <LegalInlineLink href={urls.cap553} />,
    lawCap71: <LegalInlineLink href={urls.cap71} />,
    lawCap457: <LegalInlineLink href={urls.cap457} />,
    lawCap458: <LegalInlineLink href={urls.cap458} />,
    pcpdContact: <LegalInlineLink href="https://www.pcpd.org.hk/english/contact_us/contact_us.html" />,
    pcpdTransfers: <LegalInlineLink href="https://www.pcpd.org.hk/english/resources_centre/publications/files/guidance_model_contractual_clauses.pdf" />,
  }
}
