# PathLab Frontend Source

> **Note**: For complete project documentation, see [Project Root README](../../../../../README.md)

This directory contains the source code for the PathLab frontend React application.

## Directory Structure

```
src/
├── components/          # Reusable UI components
│   ├── Layout.tsx           # Main layout (sidebar navigation)
│   ├── WSIViewer.tsx        # OpenSeadragon wrapper
│   ├── PageHeader.tsx       # Page header component
│   └── ...
├── pages/               # Page components
│   ├── LoginPage.tsx             # Login welcome page (default)
│   ├── DashboardPage.tsx         # Dashboard overview
│   ├── AIChatPage.tsx            # AI assistant
│   ├── ToolsPage.tsx             # Utility tools
│   ├── ListPage.tsx              # Slide browser (/wsi-list)
│   ├── DetailPage.tsx            # WSI viewer (/wsi/:wsi_id)
│   ├── UploadPage.tsx            # Register slide (/register)
│   ├── NewTaskPage.tsx           # Task configuration (/task-setup)
│   ├── TaskListPage.tsx          # Task list (/task-list)
│   ├── TaskDetailPage.tsx        # Task details (/task/:task_id)
│   ├── ResultsViewerPage.tsx     # Results viewer (/results)
│   ├── ReportGeneratorPage.tsx   # Report generator (/reports)
│   ├── StorageManagementPage.tsx # Storage management (/storage)
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

## Page Routes

| Route | Page | Description |
|-------|------|-------------|
| `/` `/login` | LoginPage | Login welcome page |
| `/dashboard` | DashboardPage | Dashboard |
| `/ai-chat` | AIChatPage | AI assistant |
| `/tools` | ToolsPage | Utility tools |
| `/task-setup` | NewTaskPage | Task configuration |
| `/task-list` | TaskListPage | Task list |
| `/task/:task_id` | TaskDetailPage | Task details |
| `/wsi-list` | ListPage | Slide browser |
| `/wsi/:wsi_id` | DetailPage | WSI viewer |
| `/register` | UploadPage | Register slide |
| `/results` | ResultsViewerPage | Results viewer |
| `/reports` | ReportGeneratorPage | Report generator |
| `/storage` | StorageManagementPage | Storage management |
| `/settings` | SettingsPage | System settings |

## API Integration

The frontend obtains dynamic port via Electron preload script to communicate with Python backend:

```typescript
// Get backend API URL
const backendUrl = await window.api.getBackendUrl()
// Returns: http://127.0.0.1:48427 (port dynamically allocated)
```

## Related Documentation

- [Frontend README](../README.md) - Detailed frontend documentation
- [Project README](../../../../../README.md) - Complete project documentation
- [Backend README](../../../../server/README.md) - Python backend documentation
