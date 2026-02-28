# PathLab Frontend Source

> 📌 PathLab 支持两种运行模式：**网页端**（`npm run dev`）和**本地端**（Electron 打包）

This directory contains the source code for the PathLab frontend React application.

## Directory Structure

```
src/
├── components/          # Reusable UI components
│   ├── Layout.tsx           # Main layout (sidebar navigation)
│   ├── WSIViewer.tsx        # OpenSeadragon wrapper
│   ├── PageHeader.tsx       # Page header component
│   ├── HeatmapOverlay.tsx  # Attention heatmap overlay
│   └── ...
├── pages/               # Page components (14 pages)
│   ├── IntroductionPage.tsx      # Product introduction (/)
│   ├── LoginPage.tsx             # Login welcome page (/login)
│   ├── AIChatPage.tsx            # AI assistant (/dashboard)
│   ├── ToolsPage.tsx             # Utility tools
│   ├── ListPage.tsx              # Slide browser (/wsi-list)
│   ├── WSIViewerPage.tsx         # WSI viewer (/wsi/:wsi_id, fullscreen)
│   ├── UploadPage.tsx            # Upload/register slide
│   ├── NewTaskPage.tsx           # Task configuration (/task-setup)
│   ├── TaskListPage.tsx          # Task list (/task-list)
│   ├── TaskDetailPage.tsx        # Task details (/task/:task_id)
│   ├── ResultsViewerPage.tsx     # Results viewer (/results)
│   ├── ReportGeneratorPage.tsx   # Report generator (/reports)
│   ├── StorageManagementPage.tsx  # Storage management (in Settings tab)
│   └── SettingsPage.tsx          # System settings (/settings)
├── contexts/            # React Context
│   ├── AuthContext.tsx           # Authentication state management
│   └── BackgroundTaskContext.tsx # Background task management
├── api.ts               # Backend API client
├── config.ts            # Environment configuration
├── App.tsx              # Root component (routing)
├── main.tsx             # Application entry point
└── index.css            # Global styles + Tailwind
```

## Technology Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite 5
- **Routing**: React Router v6
- **Styling**: Tailwind CSS
- **WSI Viewer**: OpenSeadragon
- **State Management**: React Hooks + Context

## Page Routes (14 pages)

| Route | Page | Description |
|-------|------|-------------|
| `/` | IntroductionPage | Product introduction page (public) |
| `/login` | LoginPage | Login welcome page (public) |
| `/dashboard` | AIChatPage | AI assistant (SSE streaming) |
| `/tools` | ToolsPage | Utility tools |
| `/settings` | SettingsPage | System settings (with Storage tab) |
| `/task-setup` | NewTaskPage | Task configuration |
| `/task-list` | TaskListPage | Task list |
| `/task/:task_id` | TaskDetailPage | Task details |
| `/wsi-list` | ListPage | Slide browser |
| `/wsi/:wsi_id` | WSIViewerPage | WSI viewer (fullscreen) |
| `/register` | UploadPage | Register/upload slide |
| `/results` | ResultsViewerPage | Results viewer |
| `/reports` | ReportGeneratorPage | Report generator |

> Note: All routes except `/` and `/login` are protected and require authentication.

## API Integration

The frontend obtains dynamic port via Electron preload script to communicate with Python backend:

```typescript
// Get backend API URL
const backendUrl = await window.api.getBackendUrl()
// Returns: http://127.0.0.1:48427 (port dynamically allocated)
```

## Supported AI Models

### Feature Extractors (19 models)

- ResNet50, ViT-Large (ImageNet)
- UNI, UNI2, CONCH, CONCH 1.5 (Mahmood Lab)
- Virchow, Virchow2 (Paige AI)
- H-Optimus-0, H-Optimus-1 (Bioptimus)
- Phikon, Phikon2 (Owkin)
- PLIP, PathoCLIP (PathLAIA)
- OpenMidnight (SophontAI)
- mSTAR, GPFM, SmartCCS, SmartCyto (HKUST Smart Lab)

### MIL Aggregators (8 models)

- ABMIL, MeanMIL, MaxMIL
- DSMIL, DTFDMIL
- CLAM-SB, CLAM-MB
- TransMIL

## Related Documentation

- [Frontend README](../README.md) - Detailed frontend documentation
- [Project README](../../../../../README.md) - Complete project documentation
- [Backend README](../../../../server/README.md) - Python backend documentation
