import { useTranslation } from 'react-i18next'
import { Lock, Server, History, Globe } from 'lucide-react'

export function TrustDeploymentSection() {
  const { t } = useTranslation()

  const cards = [
    {
      icon: Lock,
      title: 'landing.trust.privacy.title',
      desc: 'landing.trust.privacy.desc',
      defaultTitle: 'Data Privacy Control',
      defaultDesc: 'Granular visibility settings for your private datasets.'
    },
    {
      icon: Server,
      title: 'landing.trust.deployment.title',
      desc: 'landing.trust.deployment.desc',
      defaultTitle: 'Secure Execution',
      defaultDesc: 'Configured exclusively within your authorized environments.'
    },
    {
      icon: History,
      title: 'landing.trust.audit.title',
      desc: 'landing.trust.audit.desc',
      defaultTitle: 'Verifiable Results',
      defaultDesc: 'Full task logs and verifiable output for every model run.'
    },
    {
      icon: Globe,
      title: 'landing.trust.i18n.title',
      desc: 'landing.trust.i18n.desc',
      defaultTitle: 'Global Usability',
      defaultDesc: 'Built-in support for multiple languages without broken layouts.'
    }
  ]

  return (
    <section className="py-12 sm:py-16 lg:py-24 border-t border-[color:var(--landing-border)] bg-[#F7FBFD]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="text-center mb-8 sm:mb-12 lg:mb-16">
          <h2 className="text-3xl font-bold text-[color:var(--landing-text-primary)] mb-4">
            {t('landing.trust.header', 'Ready for clinical environments')}
          </h2>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {cards.map((card) => {
            const Icon = card.icon
            return (
              <div key={card.title} className="bg-white border border-[color:var(--landing-border)] rounded-2xl p-6 hover:shadow-md transition-all flex items-start gap-4">
                <div className="p-3 bg-[#F1F7FB] rounded-xl shadow-sm border border-[color:var(--landing-border)]">
                  <Icon className="w-6 h-6 text-[color:var(--landing-primary)]" />
                </div>
                <div>
                  <h4 className="font-semibold text-[color:var(--landing-text-primary)] mb-2">
                    {t(card.title, card.defaultTitle)}
                  </h4>
                  <p className="text-sm text-[color:var(--landing-text-secondary)] leading-relaxed">
                    {t(card.desc, card.defaultDesc)}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
