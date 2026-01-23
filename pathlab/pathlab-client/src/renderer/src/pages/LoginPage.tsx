/**
 * PathLab Login Page
 *
 * Landing page with OAuth login integration to PathLab Server.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Microscope, Brain, Shield, Zap, LogIn, UserPlus, Loader2, FlaskConical } from 'lucide-react'
import { Button } from '../components/ui/button'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login, signup, demoLogin, isLoading, error, isLoggedIn } = useAuth()
  const [showDisclaimer, setShowDisclaimer] = React.useState(false)

  // If already logged in, redirect to dashboard
  React.useEffect(() => {
    if (isLoggedIn) {
      navigate('/dashboard')
    }
  }, [isLoggedIn, navigate])

  const handleLogin = async () => {
    await login()
  }

  const handleSignup = async () => {
    await signup()
  }

  const handleDemoLoginClick = () => {
    setShowDisclaimer(true)
  }

  const handleDisclaimerAgree = () => {
    setShowDisclaimer(false)
    demoLogin()
    navigate('/dashboard')
  }

  const features = [
    {
      icon: Microscope,
      title: 'WSI Visualization',
      description: 'View and navigate multi-gigapixel whole slide images with smooth pan and zoom',
    },
    {
      icon: Brain,
      title: 'AI-Powered Analysis',
      description: 'Train and deploy deep learning models for pathology classification',
    },
    {
      icon: Shield,
      title: 'Privacy First',
      description: 'Your data never leaves your machine - models come to the data',
    },
    {
      icon: Zap,
      title: 'Smart Assistant',
      description: 'Describe your research in natural language, let AI set up the task',
    },
  ]

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-gray-100 to-slate-200 flex flex-col">
      {/* Header */}
      <header className="p-6">
        <img
          src="/images/pathlab-logo.png"
          alt="PathLab"
          className="h-16 w-auto"
        />
      </header>

      {/* Main Content */}
      <main className="flex-1 flex items-center justify-center px-4 py-8 sm:px-6 sm:py-12">
        <div className="max-w-6xl w-full grid lg:grid-cols-2 gap-8 lg:gap-12 items-center">
          {/* Left: Hero Content */}
          <div className="text-center lg:text-left">
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-slate-800 mb-4 sm:mb-6 leading-tight">
              Digital Pathology
              <br />
              <span className="bg-gradient-to-r from-blue-600 via-cyan-600 to-teal-600 bg-clip-text text-transparent">
                Powered by AI
              </span>
            </h2>
            <p className="text-base sm:text-lg text-slate-600 mb-6 sm:mb-8 leading-relaxed">
              PathLab is your local AI workstation for pathology research.
              Train models, analyze files, and generate insights - all while keeping your data private.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 justify-center lg:justify-start">
              <Button
                onClick={handleDemoLoginClick}
                className="flex items-center justify-center gap-2 px-6 py-4 sm:px-8 sm:py-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all text-sm sm:text-base"
              >
                <FlaskConical className="w-5 h-5" />
                Demo Login
              </Button>
              <Button
                onClick={handleLogin}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-6 py-4 sm:px-8 sm:py-6 bg-gradient-to-r from-blue-500 to-cyan-600 text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-105 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm sm:text-base"
              >
                {isLoading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <LogIn className="w-5 h-5" />
                )}
                Login with Server
              </Button>
            </div>

            {/* Secondary Actions */}
            <div className="mt-4 flex gap-4 justify-center lg:justify-start">
              <Button
                variant="secondary"
                onClick={handleSignup}
                disabled={isLoading}
                className="flex items-center justify-center gap-2 px-6 py-3 bg-slate-200 text-slate-700 font-medium rounded-lg border border-slate-300 hover:bg-slate-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                <UserPlus className="w-4 h-4" />
                Create Account
              </Button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="mt-4 p-4 bg-red-100 border border-red-300 rounded-lg text-red-600 text-sm">
                {error}
              </div>
            )}
          </div>

          {/* Right: Feature Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {features.map((feature) => {
              const Icon = feature.icon
              return (
                <div
                  key={feature.title}
                  className="p-6 bg-white backdrop-blur-sm rounded-2xl border border-slate-200 hover:bg-slate-50 transition-colors shadow-sm"
                >
                  <div className="w-12 h-12 bg-gradient-to-br from-blue-100 to-cyan-100 rounded-xl flex items-center justify-center mb-4">
                    <Icon className="w-6 h-6 text-blue-600" />
                  </div>
                  <h3 className="text-lg font-semibold text-slate-800 mb-2">{feature.title}</h3>
                  <p className="text-sm text-slate-500">{feature.description}</p>
                </div>
              )
            })}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="p-6 text-center text-slate-500 text-sm">
        <p>© 2025 PathLab. Privacy-first AI for digital pathology.</p>
      </footer>

      {showDisclaimer && (
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
                  <span>Operator: Cheng Jin (SmartLab)</span>
                  <span>Contact: cjinag@connect.ust.hk</span>
                </div>
              </div>

              <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 text-blue-900 text-xs italic">
                <strong>Scope:</strong> These Terms govern PathLab’s local Workbench application, AI verification tools, and related services (collectively, the “Services”).
              </div>

              <div className="space-y-4">
                <section>
                  <h4 className="font-bold text-slate-800 mb-1">1. Acceptance</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>1.1 By registering, signing in, downloading, installing, accessing, or using the Services, you acknowledge that you have read, understood, and agree to be bound by these Terms.</li>
                    <li>1.2 If you use the Services on behalf of an organization, you represent that you have authority to bind that organization, and the organization is responsible for your use.</li>
                    <li>1.3 If you do not agree to these Terms, do not use the Services.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">2. Eligibility and Compliance</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>2.1 You must have the legal capacity to enter into and comply with these Terms and must comply with applicable laws, industry rules, institutional policies, and ethics review requirements where applicable.</li>
                    <li>2.2 You will not use the Services for any unlawful, harmful, infringing, discriminatory, or otherwise improper purpose.</li>
                    <li>2.3 Where applicable, you must comply with export controls and sanctions and must not use the Services in prohibited locations or for prohibited end uses.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">3. Definitions</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>3.1 <strong>Platform / We</strong> means SmartLab and its operator.</li>
                    <li>3.2 <strong>User / You</strong> means any individual or entity that registers, signs in, accesses, or uses the Services.</li>
                    <li>3.3 <strong>Workbench (Client)</strong> means the local desktop application (for example, Electron with a Python sidecar) used for slide viewing, local inference, visualization, and reporting.</li>
                    <li>3.4 <strong>Auth Server</strong> means the authentication service (e.g., Casdoor) used to verify user identity.</li>
                    <li>3.5 <strong>Model</strong> means any machine learning model and related artifacts, including weights, configuration files (including model_config.json), inference or training scripts, metadata, and derivatives.</li>
                    <li>3.6 <strong>Data</strong> means any data uploaded, imported, generated, provided, or processed through the Services, including WSI (whole slide images), derived tiles, thumbnails, annotations, task metadata, and outputs.</li>
                    <li>3.7 <strong>Outputs</strong> means any results generated or displayed by the Services, including predictions, heatmaps, reports, metrics, logs, and summaries.</li>
                    <li>3.8 <strong>Content</strong> means any text, images, models, scripts, comments, links, or other materials you upload, submit, publish, or display through the Services.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">4. Accounts, Authentication, and Security</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>4.1 Certain features require an account and authentication (via OAuth/Casdoor). You will provide accurate and up to date information.</li>
                    <li>4.2 You are responsible for safeguarding credentials, tokens, and device security and must not share, lend, or transfer accounts.</li>
                    <li>4.3 You are responsible for losses arising from compromised devices, misconfiguration, or improper access controls.</li>
                    <li>4.4 We may apply security measures such as verification, access restrictions, auditing, and risk controls.</li>
                  </ul>
                </section>

                 <section>
                  <h4 className="font-bold text-slate-800 mb-1">5. Services</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>5.1 <strong>Local Inference and Viewing:</strong> The Workbench supports WSI visualization, tiling, local inference, and overlay visualization of results entirely on your local machine.</li>
                    <li>5.2 <strong>Training and Task System:</strong> The Workbench may support creating and running local training tasks. Outcomes may vary based on data, configuration, environment, and randomness.</li>
                    <li>5.3 <strong>AI Chat and Wizard:</strong> The Services may provide an LLM-based assistant for parameter extraction, workflow guidance, and report assistance.</li>
                    <li>5.4 <strong>Report Generation:</strong> The Services may provide auto-generated analysis reports or templates; Outputs may vary by model and inputs.</li>
                    <li>5.5 <strong>Updates and Changes:</strong> We may update, modify, suspend, or discontinue features, APIs, models, algorithms, Outputs, or dependencies.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">6. Local Data Privacy and Compliance</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>6.1 <strong>Responsibility:</strong> You are solely responsible for local security, access controls, backup, retention, and deletion of your Data in accordance with your institutional requirements and applicable laws (e.g., HIPAA, GDPR).</li>
                    <li>6.2 <strong>No Central Storage:</strong> The Platform does not provide cloud storage for your whole slide images. You must maintain your own local storage and backups.</li>
                    <li>6.3 <strong>Data Exports:</strong> Any reports or data you choose to export or share are your sole responsibility.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">7. Your Content, Data, and License to Us</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>7.1 <strong>Your Ownership:</strong> As between you and the Platform, you retain rights to your Content and Data to the extent you own them.</li>
                    <li>7.2 <strong>License to the Platform:</strong> You grant us a limited license to process your Data locally on your device solely for the purpose of providing the Services (e.g., running inference, generating reports). Usage telemetry may be collected as described in Section 15.</li>
                    <li>7.3 <strong>Compliance:</strong> You represent that you have all necessary rights and permissions and that your Content and Data do not infringe third-party rights and comply with applicable law and institutional policies.</li>
                    <li>7.4 <strong>Sensitive Data Restrictions:</strong> Unless properly authorized and compliant, you must not submit patient-identifiable information in AI chat prompts, feedback forms, or other channels that may leave your local environment.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">8. Model Usage and Restrictions</h4>
                   <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>8.1 <strong>License:</strong> Models provided with the Service are for use within the Workbench only, unless explicitly stated otherwise.</li>
                    <li>8.2 <strong>No Reverse Engineering:</strong> You must not reverse engineer, decompile, or attempt to extract proprietary model weights or architectures if they are protected.</li>
                    <li>8.3 <strong>Research Use:</strong> Unless certified, models are for Research Use Only and not for clinical diagnosis.</li>
                  </ul>
                </section>

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

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">10. Third-Party Services and Open Source</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>10.1 The Services may integrate third-party services or rely on open source components (for example OpenCSG, Docker, databases, and UI components). Those components are governed by their respective licenses and terms.</li>
                    <li>10.2 We do not warrant the availability, security, or compliance of third-party services. To the extent permitted by law, we are not liable for interruptions or losses caused by third parties.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">11. Fees, Subscriptions, and Taxes</h4>
                   <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>11.1 The Platform may offer free and paid features. If paid services are introduced, we will disclose pricing, billing, subscription cycles, refund rules, and tax allocation in advance.</li>
                    <li>11.2 Unless explicitly stated otherwise, fees are non-refundable.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">12. Intellectual Property and Feedback</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>12.1 The Platform and its software, UI, trademarks, documentation, and non-user-submitted content are owned by the Platform or its licensors.</li>
                    <li>12.2 You may provide feedback or suggestions, and we may use them without obligation to you.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">13. Privacy, Telemetry, and Logs</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>13.1 We may collect minimally necessary telemetry and logs for security, auditing, troubleshooting, and product improvement, such as feature usage events, error logs, and performance metrics.</li>
                    <li>13.2 We will use reasonable measures to apply access controls and encrypted storage for telemetry and log data.</li>
                    <li>13.3 Our Privacy Policy governs personal data handling and forms part of these Terms.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">14. Medical and Model Output Notices</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>14.1 <strong>No Medical Advice:</strong> Outputs are for informational purposes only and do not constitute medical advice, diagnosis, or treatment.</li>
                    <li>14.2 <strong>Human Review Required:</strong> Any clinical decision must be independently evaluated and confirmed by qualified medical professionals.</li>
                    <li>14.3 <strong>No Accuracy Guarantee:</strong> Models may be biased or incorrect and may not generalize across populations, scanners, stains, and workflows.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">15. Disclaimers</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>15.1 To the maximum extent permitted by law, the Services are provided “as is” and “as available” without warranties of any kind.</li>
                    <li>15.2 We do not warrant uninterrupted availability, error-free operation, or fitness for your particular needs.</li>
                    <li>15.3 You assume all risks associated with use of the Services.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">16. Limitation of Liability</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>16.1 To the maximum extent permitted by law, the Platform and its developers are not liable for indirect, incidental, special, punitive, or consequential damages, including loss of profits, goodwill, business interruption, or data loss.</li>
                    <li>16.2 Our total liability (if any) arising out of or related to the Services will not exceed the total fees you actually paid to us for the Services in the 12 months preceding the event giving rise to the claim; if you paid no fees, liability will not exceed 1,000 HKD or equivalent, whichever is lower.</li>
                    <li>16.3 Some jurisdictions do not allow certain limitations, so these limitations may not apply to you to the extent prohibited.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">17. Indemnification</h4>
                  <p className="text-xs">
                    You agree to indemnify and hold harmless the Platform, its affiliates, employees, and partners from any claims, damages, liabilities, costs, and expenses (including reasonable attorneys’ fees) arising from your breach of these Terms, unlawful use of the Services, infringement of third-party rights, or submission of malicious content.
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

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">19. Changes to These Terms</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>19.1 We may update these Terms for compliance, security, or product iteration and will provide reasonable notice (for example in-product notice or email) where appropriate.</li>
                    <li>19.2 Continued use after the effective date of changes constitutes acceptance of the updated Terms.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">20. Governing Law and Dispute Resolution</h4>
                  <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>20.1 These Terms are governed by the laws of Hong Kong.</li>
                    <li>20.2 Disputes will first be attempted to be resolved through good-faith negotiation. If unresolved, disputes will be resolved by arbitration at the Hong Kong International Arbitration Centre or litigation in the courts of Hong Kong, depending on the mechanism you select and apply consistently.</li>
                    <li>20.3 You agree that electronic communications and records are admissible evidence.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-bold text-slate-800 mb-1">21. Miscellaneous</h4>
                   <ul className="list-disc pl-5 space-y-1 text-xs">
                    <li>21.1 <strong>Severability:</strong> If any provision is invalid, the remainder remains in effect.</li>
                    <li>21.2 <strong>No Waiver:</strong> Failure to enforce a provision is not a waiver.</li>
                    <li>21.3 <strong>Assignment:</strong> You may not assign these Terms without our written consent. We may assign in connection with merger, reorganization, or asset transfer.</li>
                    <li>21.4 <strong>Entire Agreement:</strong> These Terms, the Privacy Policy, and posted rules constitute the entire agreement regarding the Services.</li>
                  </ul>
                </section>
              </div>
            </div>
            <div className="p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100">
              <Button
                variant="ghost"
                onClick={() => setShowDisclaimer(false)}
                className="text-slate-600 hover:text-slate-900 hover:bg-slate-200"
              >
                Cancel
              </Button>
              <Button
                onClick={handleDisclaimerAgree}
                className="bg-blue-600 hover:bg-blue-700 text-white shadow-md hover:shadow-lg transition-all"
              >
                I Agree & Continue
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

