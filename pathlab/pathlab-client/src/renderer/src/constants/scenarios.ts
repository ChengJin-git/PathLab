import { Rocket, Database, FlaskConical, Microscope } from 'lucide-react'

export const SCENARIO_CARDS = [
  {
    id: 'start-fresh',
    icon: Rocket,
    titleKey: 'aiChat.scenarioCards.startFresh.title',
    descriptionKey: 'aiChat.scenarioCards.startFresh.description',
    promptKey: 'aiChat.scenarioCards.startFresh.prompt',
    color: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-50 hover:bg-blue-100',
    iconColor: 'text-blue-600'
  },
  {
    id: 'train-model',
    icon: Database,
    titleKey: 'aiChat.scenarioCards.trainModel.title',
    descriptionKey: 'aiChat.scenarioCards.trainModel.description',
    promptKey: 'aiChat.scenarioCards.trainModel.prompt',
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-50 hover:bg-purple-100',
    iconColor: 'text-purple-600'
  },
  {
    id: 'test-model',
    icon: FlaskConical,
    titleKey: 'aiChat.scenarioCards.testModel.title',
    descriptionKey: 'aiChat.scenarioCards.testModel.description',
    promptKey: 'aiChat.scenarioCards.testModel.prompt',
    color: 'from-green-500 to-emerald-500',
    bgColor: 'bg-green-50 hover:bg-green-100',
    iconColor: 'text-green-600'
  },
  {
    id: 'browse-images',
    icon: Microscope,
    titleKey: 'aiChat.scenarioCards.browseImages.title',
    descriptionKey: 'aiChat.scenarioCards.browseImages.description',
    promptKey: 'aiChat.scenarioCards.browseImages.prompt',
    color: 'from-orange-500 to-amber-500',
    bgColor: 'bg-orange-50 hover:bg-orange-100',
    iconColor: 'text-orange-600'
  }
]

