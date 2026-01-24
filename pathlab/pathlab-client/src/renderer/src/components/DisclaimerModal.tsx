/**
 * Disclaimer Modal Component
 *
 * Shows the terms of service and user agreement after user logs in
 * if they haven't accepted the agreement yet.
 */

import React from 'react'
import { Shield, Loader2 } from 'lucide-react'
import { Button } from './ui/button'

interface DisclaimerModalProps {
  isOpen: boolean
  isLoading: boolean
  onAccept: () => void
  onDecline: () => void
}

export function DisclaimerModal({ isOpen, isLoading, onAccept, onDecline }: DisclaimerModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200">
        <div className="p-6 border-b border-gray-100 bg-gray-50/50">
          <h3 className="text-xl font-bold text-gray-900 flex items-center gap-2">
            <Shield className="w-5 h-5 text-blue-600" />
            User Agreement & Disclaimer
          </h3>
        </div>
        <div className="p-6 max-h-[60vh] overflow-y-auto text-slate-600 space-y-6 text-sm leading-relaxed scrollbar-thin scrollbar-thumb-gray-200 scrollbar-track-transparent">
          <div className="text-center border-b border-gray-100 pb-4">
            <h2 className="text-xl font-bold text-slate-900">PathLab Terms of Service and User Agreement</h2>
            <div className="mt-2 text-xs text-slate-500 flex flex-col gap-1">
              <span>Operator: Cheng Jin and Yihui Wang (SmartLab)</span>
              <span>Contact: <a href="mailto:cjinag@connect.ust.hk">cjinag@connect.ust.hk</a></span>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 text-blue-900 text-xs italic">
            <strong>Scope:</strong> These Terms govern PathLab&apos;s local Workbench application, AI verification tools, and related services (collectively, the &quot;Services&quot;).
          </div>

          <div className="space-y-4">
            <TermsSection title="1. Acceptance" items={[
              "1.1 By registering, signing in, downloading, installing, accessing, or using the Services, you acknowledge that you have read, understood, and agree to be bound by these Terms.",
              "1.2 If you use the Services on behalf of an organization, you represent that you have authority to bind that organization, and the organization is responsible for your use.",
              "1.3 If you do not agree to these Terms, do not use the Services."
            ]} />

            <TermsSection title="2. Eligibility and Compliance" items={[
              "2.1 You must have the legal capacity to enter into and comply with these Terms and must comply with applicable laws, industry rules, institutional policies, and ethics review requirements where applicable.",
              "2.2 You will not use the Services for any unlawful, harmful, infringing, discriminatory, or otherwise improper purpose.",
              "2.3 Where applicable, you must comply with export controls and sanctions and must not use the Services in prohibited locations or for prohibited end uses."
            ]} />

            <TermsSection title="3. Definitions" items={[
              "3.1 Platform / We means SmartLab and its operator.",
              "3.2 User / You means any individual or entity that registers, signs in, accesses, or uses the Services.",
              "3.3 Workbench (Client) means the local desktop application (for example, Electron with a Python sidecar) used for slide viewing, local inference, visualization, and reporting.",
              "3.4 Auth Server means the authentication service (e.g., Casdoor) used to verify user identity.",
              "3.5 Model means any machine learning model and related artifacts, including weights, configuration files (including model_config.json), inference or training scripts, metadata, and derivatives.",
              "3.6 Data means any data uploaded, imported, generated, provided, or processed through the Services, including WSI (whole slide images), derived tiles, thumbnails, annotations, task metadata, and outputs.",
              "3.7 Outputs means any results generated or displayed by the Services, including predictions, heatmaps, reports, metrics, logs, and summaries.",
              "3.8 Content means any text, images, models, scripts, comments, links, or other materials you upload, submit, publish, or display through the Services."
            ]} />

            <TermsSection title="4. Accounts, Authentication, and Security" items={[
              "4.1 Certain features require an account and authentication (via OAuth/Casdoor). You will provide accurate and up to date information.",
              "4.2 You are responsible for safeguarding credentials, tokens, and device security and must not share, lend, or transfer accounts.",
              "4.3 You are responsible for losses arising from compromised devices, misconfiguration, or improper access controls.",
              "4.4 We may apply security measures such as verification, access restrictions, auditing, and risk controls."
            ]} />

            <TermsSection title="5. Services" items={[
              "5.1 Local Inference and Viewing: The Workbench supports WSI visualization, tiling, local inference, and overlay visualization of results entirely on your local machine.",
              "5.2 Training and Task System: The Workbench may support creating and running local training tasks. Outcomes may vary based on data, configuration, environment, and randomness.",
              "5.3 AI Chat and Wizard: The Services may provide an LLM-based assistant for parameter extraction, workflow guidance, and report assistance.",
              "5.4 Report Generation: The Services may provide auto-generated analysis reports or templates; Outputs may vary by model and inputs.",
              "5.5 Updates and Changes: We may update, modify, suspend, or discontinue features, APIs, models, algorithms, Outputs, or dependencies."
            ]} />

            <TermsSection title="6. Local Data Privacy and Compliance" items={[
              "6.1 Responsibility: You are solely responsible for local security, access controls, backup, retention, and deletion of your Data in accordance with your institutional requirements and applicable laws (e.g., HIPAA, GDPR).",
              "6.2 No Central Storage: The Platform does not provide cloud storage for your whole slide images. You must maintain your own local storage and backups.",
              "6.3 Data Exports: Any reports or data you choose to export or share are your sole responsibility."
            ]} />

            <TermsSection title="7. Your Content, Data, and License to Us" items={[
              "7.1 Your Ownership: As between you and the Platform, you retain rights to your Content and Data to the extent you own them.",
              "7.2 License to the Platform: You grant us a limited license to process your Data locally on your device solely for the purpose of providing the Services (e.g., running inference, generating reports). Usage telemetry may be collected as described in Section 15.",
              "7.3 Compliance: You represent that you have all necessary rights and permissions and that your Content and Data do not infringe third-party rights and comply with applicable law and institutional policies.",
              "7.4 Sensitive Data Restrictions: Unless properly authorized and compliant, you must not submit patient-identifiable information in AI chat prompts, feedback forms, or other channels that may leave your local environment."
            ]} />

            <TermsSection title="8. Model Usage and Restrictions" items={[
              "8.1 License: Models provided with the Service are for use within the Workbench only, unless explicitly stated otherwise.",
              "8.2 No Reverse Engineering: You must not reverse engineer, decompile, or attempt to extract proprietary model weights or architectures if they are protected.",
              "8.3 Research Use: Unless certified, models are for Research Use Only and not for clinical diagnosis."
            ]} />

            <section>
              <h4 className="font-bold text-slate-800 mb-1">9. Acceptable Use Policy</h4>
              <ul className="list-disc pl-5 space-y-1 text-xs">
                <li>9.1 You must not:
                  <ul className="list-[circle] pl-5 mt-1">
                    <li>(a) disrupt or interfere with the Auth Server or update services;</li>
                    <li>(b) distribute malware or perform unauthorized security testing;</li>
                    <li>(c) impersonate others or use fraudulent credentials;</li>
                    <li>(d) engage in unlawful, harmful, harassing, discriminatory, or improper conduct;</li>
                    <li>(e) use the Services to generate or distribute illegal content.</li>
                  </ul>
                </li>
                <li>9.2 We may enforce these Terms through warnings, account suspension, termination, and legal action where appropriate.</li>
              </ul>
            </section>

            <TermsSection title="10. Third-Party Services and Open Source" items={[
              "10.1 The Services may integrate third-party services or rely on open source components (for example OpenCSG, Docker, databases, and UI components). Those components are governed by their respective licenses and terms.",
              "10.2 We do not warrant the availability, security, or compliance of third-party services. To the extent permitted by law, we are not liable for interruptions or losses caused by third parties."
            ]} />

            <TermsSection title="11. Fees, Subscriptions, and Taxes" items={[
              "11.1 The Platform may offer free and paid features. If paid services are introduced, we will disclose pricing, billing, subscription cycles, refund rules, and tax allocation in advance.",
              "11.2 Unless explicitly stated otherwise, fees are non-refundable."
            ]} />

            <TermsSection title="12. Intellectual Property and Feedback" items={[
              "12.1 The Platform and its software, UI, trademarks, documentation, and non-user-submitted content are owned by the Platform or its licensors.",
              "12.2 You may provide feedback or suggestions, and we may use them without obligation to you."
            ]} />

            <TermsSection title="13. Privacy, Telemetry, and Logs" items={[
              "13.1 We may collect minimally necessary telemetry and logs for security, auditing, troubleshooting, and product improvement, such as feature usage events, error logs, and performance metrics.",
              "13.2 We will use reasonable measures to apply access controls and encrypted storage for telemetry and log data.",
              "13.3 Our Privacy Policy governs personal data handling and forms part of these Terms."
            ]} />

            <TermsSection title="14. Medical and Model Output Notices" items={[
              "14.1 No Medical Advice: Outputs are for informational purposes only and do not constitute medical advice, diagnosis, or treatment.",
              "14.2 Human Review Required: Any clinical decision must be independently evaluated and confirmed by qualified medical professionals.",
              "14.3 No Accuracy Guarantee: Models may be biased or incorrect and may not generalize across populations, scanners, stains, and workflows."
            ]} />

            <TermsSection title="15. Disclaimers" items={[
              "15.1 To the maximum extent permitted by law, the Services are provided \"as is\" and \"as available\" without warranties of any kind.",
              "15.2 We do not warrant uninterrupted availability, error-free operation, or fitness for your particular needs.",
              "15.3 You assume all risks associated with use of the Services."
            ]} />

            <TermsSection title="16. Limitation of Liability" items={[
              "16.1 To the maximum extent permitted by law, the Platform and its developers are not liable for indirect, incidental, special, punitive, or consequential damages, including loss of profits, goodwill, business interruption, or data loss.",
              "16.2 Our total liability (if any) arising out of or related to the Services will not exceed the total fees you actually paid to us for the Services in the 12 months preceding the event giving rise to the claim; if you paid no fees, liability will not exceed 1,000 HKD or equivalent, whichever is lower.",
              "16.3 Some jurisdictions do not allow certain limitations, so these limitations may not apply to you to the extent prohibited."
            ]} />

            <section>
              <h4 className="font-bold text-slate-800 mb-1">17. Indemnification</h4>
              <p className="text-xs">
                You agree to indemnify and hold harmless the Platform, its affiliates, employees, and partners from any claims, damages, liabilities, costs, and expenses (including reasonable attorneys&apos; fees) arising from your breach of these Terms, unlawful use of the Services, infringement of third-party rights, or submission of malicious content.
              </p>
            </section>

            <section>
              <h4 className="font-bold text-slate-800 mb-1">18. Suspension and Termination</h4>
              <ul className="list-disc pl-5 space-y-1 text-xs">
                <li>18.1 We may suspend or terminate your access in whole or in part if:
                  <ul className="list-[circle] pl-5 mt-1">
                    <li>(a) you breach these Terms;</li>
                    <li>(b) you pose security, cheating, or abuse risks;</li>
                    <li>(c) required by law or regulators;</li>
                    <li>(d) necessary to protect the Platform, users, or third parties.</li>
                  </ul>
                </li>
                <li>18.2 Upon termination, your access ends. Provisions that by their nature should survive (including IP, disclaimers, limitation of liability, indemnification, and dispute resolution) will survive.</li>
              </ul>
            </section>

            <TermsSection title="19. Changes to These Terms" items={[
              "19.1 We may update these Terms for compliance, security, or product iteration and will provide reasonable notice (for example in-product notice or email) where appropriate.",
              "19.2 Continued use after the effective date of changes constitutes acceptance of the updated Terms."
            ]} />

            <TermsSection title="20. Governing Law and Dispute Resolution" items={[
              "20.1 These Terms are governed by the laws of Hong Kong.",
              "20.2 Disputes will first be attempted to be resolved through good-faith negotiation. If unresolved, disputes will be resolved by arbitration at the Hong Kong International Arbitration Centre or litigation in the courts of Hong Kong, depending on the mechanism you select and apply consistently.",
              "20.3 You agree that electronic communications and records are admissible evidence."
            ]} />

            <TermsSection title="21. Miscellaneous" items={[
              "21.1 Severability: If any provision is invalid, the remainder remains in effect.",
              "21.2 No Waiver: Failure to enforce a provision is not a waiver.",
              "21.3 Assignment: You may not assign these Terms without our written consent. We may assign in connection with merger, reorganization, or asset transfer.",
              "21.4 Entire Agreement: These Terms, the Privacy Policy, and posted rules constitute the entire agreement regarding the Services."
            ]} />

            <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-amber-900 text-xs">
              <strong>Important:</strong> By clicking &quot;I Agree &amp; Continue&quot;, you confirm that you have read and understood these Terms of Service, including the medical disclaimers and limitations of liability.
            </div>
          </div>
        </div>
        <div className="p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
          <Button
            variant="ghost"
            onClick={onDecline}
            disabled={isLoading}
            className="text-slate-600 hover:text-slate-900 hover:bg-slate-200"
          >
            Cancel
          </Button>
          <Button
            onClick={onAccept}
            disabled={isLoading}
            className="bg-blue-600 hover:bg-blue-700 text-white shadow-md hover:shadow-lg transition-all"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Processing...
              </>
            ) : (
              'I Agree & Continue'
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}

function TermsSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h4 className="font-bold text-slate-800 mb-1">{title}</h4>
      <ul className="list-disc pl-5 space-y-1 text-xs">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

