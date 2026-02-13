/**
 * Scenario cards for the AI Chat guided experience.
 *
 * Extracted from AIChatPage.tsx to reduce file size.
 */
import { Rocket, Database, FlaskConical, Microscope } from 'lucide-react'

export const SCENARIO_CARDS = [
  {
    id: 'start-fresh',
    icon: Rocket,
    title: 'Fresh Start',
    description: 'Begin a new pathology research project',
    prompt: 'I want to start a new pathology research project. Can you help me understand what options I have?',
    color: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-50 hover:bg-blue-100',
    iconColor: 'text-blue-600'
  },
  {
    id: 'train-model',
    icon: Database,
    title: 'Train Model',
    description: 'I have a dataset ready for training',
    prompt: 'I have a dataset of pathology images and want to train a deep learning model. What do I need to configure?',
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-50 hover:bg-purple-100',
    iconColor: 'text-purple-600'
  },
  {
    id: 'test-model',
    icon: FlaskConical,
    title: 'Test Model',
    description: 'Run inference with a trained model',
    prompt: 'I have a trained model and want to run inference. How do I proceed?',
    color: 'from-green-500 to-emerald-500',
    bgColor: 'bg-green-50 hover:bg-green-100',
    iconColor: 'text-green-600'
  },
  {
    id: 'browse-images',
    icon: Microscope,
    title: 'Browse Images',
    description: 'Browse and analyze WSI or patches',
    prompt: 'I want to browse and analyze some pathology images (WSI or patches). Can you help me find the right ones based on my needs?',
    color: 'from-orange-500 to-amber-500',
    bgColor: 'bg-orange-50 hover:bg-orange-100',
    iconColor: 'text-orange-600'
  }
]

