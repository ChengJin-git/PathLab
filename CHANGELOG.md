# Changelog

All notable changes to SmartResearch will be documented in this file.

## [0.2.0] - 2024-10-29

### Added
- **AI Assistant Page**: Natural language task setup with streaming LLM chat interface
  - Streaming responses with real-time display
  - Quick action buttons for common tasks
  - Link to structured setup for users who prefer step-by-step guidance
- **Integrated Task Workflow**: Unified NewTaskPage with complete analysis setup flow
  - Task description step
  - Model selection (ResNet50, ViT-Base, CTransPath, UNI)
  - Data selection with slide preview
  - Training simulation with progress tracking
- **Full-Screen WSI Viewer**: DetailPage now renders without layout wrapper for maximum viewing area
- **Logo and Favicon**: Modern gradient design with "SR" branding
- **Medical Professional-Friendly UI**: Replaced technical terminology across all pages
  - "WSI" → "Slide"
  - "Inference" → "Analysis"
  - "Task" → "Analysis"
  - "Feature Extraction" → "Analysis"
  - "Prediction" → "Suggestion"
  - "Probabilities" → "Confidence Scores"

### Changed
- **Navigation Menu**: Reorganized menu items
  - Moved "New Analysis" above "Slide Browser"
  - Renamed items for clarity (AI Chat → AI Assistant, WSI Browser → Slide Browser)
- **Dashboard Quick Actions**: Updated to reflect current workflow
  - Removed legacy "Select Data" and "Inference" actions
  - Added "AI Assistant" and "Settings" shortcuts
- **Layout Height**: Fixed white space issue in DetailPage by using full viewport height

### Removed
- **Legacy Pages**: Cleaned up unused components
  - InferencePage.tsx (functionality merged into ListPage)
  - TaskSetupPage.tsx (replaced by NewTaskPage)
  - TrainingDataSelectionPage.tsx (integrated into NewTaskPage)
  - TrainingPage.tsx (integrated into NewTaskPage)
- **Unused Assets**: Removed external logo.svg and favicon.svg (now using inline SVG)

### Fixed
- Layout height calculation in DetailPage causing white space below WSI viewer
- Logo display issues by switching to inline SVG
- Navigation consistency across all pages

## [0.1.0] - 2024-10-28

### Added
- Initial release with core platform features
- Microservices architecture (Gateway, WSI Service, AI Service, Frontend)
- WSI viewer with OpenSeadragon
- WSI upload functionality (single/batch/path-based)
- Basic inference API with fallback mechanism
- Metadata management from CSV
- Support for 16+ WSI formats via ASlide
- Dashboard with statistics
- WSI list management
- Settings page (placeholder)

### Infrastructure
- FastAPI backend services
- React + Vite frontend with Tailwind CSS
- Hot-reload for custom inference models
- Nginx reverse proxy configuration
- Start/stop scripts for all services

