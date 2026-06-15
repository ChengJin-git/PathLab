import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { usePathScientistTranslation } from '../../lib/usePathScientistTranslation'
import { Button } from '../ui/button'

export default function PathScientistBackButton() {
  const navigate = useNavigate()
  const { t } = usePathScientistTranslation()

  return (
    <Button
      type="button"
      variant="outline"
      className="gap-2"
      onClick={() => navigate('/dashboard')}
    >
      <ArrowLeft className="h-4 w-4" />
      {t('common.back')}
    </Button>
  )
}
