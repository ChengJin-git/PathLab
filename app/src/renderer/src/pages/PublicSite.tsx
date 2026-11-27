/** Landing and sign-in ship as one chunk, so moving between them never waits on a
 * network request or a Suspense fallback; the 3D stage moves with the visitor. */
import IntroductionPage from './IntroductionPage'
import LoginPage from './LoginPage'

export default function PublicSite({ page }: { page: 'landing' | 'login' }) {
  return page === 'landing' ? <IntroductionPage /> : <LoginPage />
}
