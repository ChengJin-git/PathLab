import { ShieldAlert, ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

export default function AccessDenied() {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh')
  const hk = /zh-(HK|TW|Hant)/i.test(i18n.language)
  return <section role="alert" className="flex min-h-[65vh] items-center justify-center bg-gray-50 px-6">
    <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
      <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-700"><ShieldAlert size={27} /></div>
      <h1 className="text-xl font-semibold text-gray-900">{zh ? (hk ? '無權限存取' : '无权限访问') : 'Access unavailable'}</h1>
      <p className="mt-3 text-sm leading-6 text-gray-600">{zh ? (hk ? '目前帳戶未獲授權使用此功能。如需開通，請聯絡管理員。' : '当前账号暂无此功能的访问权限。如需开通，请联系管理员。') : 'Your account does not have access to this feature. Please contact your administrator to request access.'}</p>
      <Link to="/datasets" className="mt-6 inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"><ArrowLeft size={15} />{zh ? (hk ? '返回資料倉庫' : '返回数据仓库') : 'Back to Data Repo'}</Link>
    </div>
  </section>
}
