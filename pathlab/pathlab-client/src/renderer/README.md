# PathLab Frontend

数字病理学研究平台前端，基于 React + TypeScript + Vite 构建。

## 🚀 运行模式

| 模式 | 启动方式 | API 地址 | 说明 |
|------|---------|---------|------|
| **网页端** (调试模式) | `npm run dev` | `http://localhost:6100` | Vite 热更新，浏览器访问 |
| **本地端** (打包模式) | Electron 打包 | 动态端口 | 桌面应用，离线可用 |

## Architecture Overview

### Technology Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite 5
- **Routing**: React Router v6
- **Styling**: Tailwind CSS
- **WSI Viewer**: OpenSeadragon (bundled locally)
- **State Management**: React Hooks (useState, useEffect)
- **HTTP Client**: Fetch API with streaming support

### Key Features

1. **WSI Viewer** - Interactive multi-gigapixel image viewer
   - Deep Zoom Image (DZI) protocol
   - Tile-based rendering for performance
   - Navigation controls and mini-map
   - Full-screen support

2. **AI Chat Assistant** - Natural language interface for research tasks
   - Streaming LLM responses
   - Task description parsing
   - Automatic parameter extraction
   - Conversation history (database-persisted)

3. **Dashboard** - System overview and statistics
   - WSI count and label distribution
   - Task status monitoring
   - Quick access to recent analyses

4. **File Browser** - WSI library management
   - Grid/list view of all slides
   - Metadata display (case ID, label, dimensions)
   - Quick navigation to viewer

5. **Analysis Setup** - Configure AI analysis tasks
   - Parameter customization (tile size, stride, model selection)
   - Device selection (CPU/GPU)
   - Real-time task submission

## Project Structure

```
pathlab/pathlab-client/src/renderer/
├── src/
│   ├── components/          # Reusable UI components
│   │   ├── Layout.tsx       # Main layout with sidebar navigation
│   │   ├── WSIViewer.tsx    # OpenSeadragon wrapper component
│   │   ├── PageHeader.tsx   # Page header component
│   │   └── ...
│   ├── pages/               # Route-level page components (15 pages)
│   │   ├── IntroductionPage.tsx      # Product introduction (/)
│   │   ├── LoginPage.tsx             # Login/welcome page (/login)
│   │   ├── DashboardPage.tsx         # System overview
│   │   ├── AIChatPage.tsx            # AI assistant interface
│   │   ├── ToolsPage.tsx             # Utility tools
│   │   ├── ListPage.tsx              # WSI browser (/wsi-list)
│   │   ├── WSIViewerPage.tsx         # WSI viewer (/wsi/:wsi_id)
│   │   ├── UploadPage.tsx            # WSI registration (/register)
│   │   ├── NewTaskPage.tsx           # Manual task setup (/task-setup)
│   │   ├── TaskListPage.tsx          # Task browser (/task-list)
│   │   ├── TaskDetailPage.tsx        # Task details (/task/:task_id)
│   │   ├── ResultsViewerPage.tsx     # Results viewer (/results)
│   │   ├── ReportGeneratorPage.tsx   # Report generator (/reports)
│   │   ├── StorageManagementPage.tsx # Storage management (/storage)
│   │   └── SettingsPage.tsx          # Configuration (/settings)
│   ├── contexts/            # React Context
│   │   ├── AuthContext.tsx           # Authentication state
│   │   └── BackgroundTaskContext.tsx # Background task management
│   ├── api.ts               # Backend API client functions
│   ├── config.ts            # Environment-based configuration
│   ├── App.tsx              # Root component with routing
│   ├── main.tsx             # Application entry point
│   └── index.css            # Global styles + Tailwind
├── public/
│   └── assets/
│       └── openseadragon/   # OpenSeadragon library (bundled)
├── .env.example             # Environment variables template
├── vite.config.ts           # Vite configuration
├── tailwind.config.js       # Tailwind CSS configuration
├── tsconfig.json            # TypeScript configuration
└── package.json             # Dependencies and scripts
```

## API Integration

The frontend communicates with the Python backend through dynamic port discovery:

### 1. Gateway Service (Dynamic Port)
- **Purpose**: Main API gateway and orchestration
- **Port Discovery**: Electron main process parses `PORT=xxxxx` from Python output
- **Endpoints**:
  - `GET /wsi` - List all WSI slides
  - `GET /wsi/{wsi_id}` - Get WSI metadata
  - `POST /tasks/wsi_classification` - Create analysis task
  - `GET /tasks/{task_id}` - Get task status
  - `GET /results/{wsi_id}` - Get analysis results
  - `POST /chat` - AI chat (streaming)
  - `GET /stats` - System statistics
  - `POST /wsi/upload/path` - Register WSI by file path
  - `GET /queue` - Get GPU task queue status

### 2. Preprocessing Service (Internal Port)
- **Purpose**: WSI file processing, tissue segmentation, patch extraction, and tile generation
- **Note**: Accessed via Gateway proxy, frontend does not call directly
- **Endpoints** (via Gateway):
  - `GET /api/wsi/{wsi_id}/dzi` - DZI descriptor
  - `GET /api/wsi/{wsi_id}/tiles/{z}/{x}_{y}.jpeg` - Image tiles
  - `GET /api/wsi/{wsi_id}/thumbnail` - Thumbnail image

### 3. AI Service (Internal Port)
- **Purpose**: AI model inference and analysis
- **Note**: Accessed via Gateway proxy, frontend does not call directly
- **Endpoints** (via Gateway):
  - `POST /api/ai/analyze` - Run AI analysis
  - `GET /api/ai/results/{wsi_id}` - Get AI results

### API Client (`src/api.ts`)

All API calls are centralized in `api.ts`:

```typescript
// Example: Streaming chat
export async function chatWithAI(
  messages: Array<{ role: 'user' | 'assistant', content: string }>,
  onChunk: (chunk: string) => void
): Promise<void>

// Example: Fetch WSI list
export async function fetchWSIList(): Promise<{ items: WSIItem[] }>

// Example: Submit analysis task
export async function analyzeWSI(wsi_id: string, params: any): Promise<{ task_id: string }>
```

## Development Setup

### Prerequisites

- Node.js 18+ (or pnpm/yarn)
- Backend services running (Gateway, WSI, AI)

### Installation

```bash
# Navigate to frontend directory
cd pathlab/pathlab-client/src/renderer

# Install dependencies
npm install
# or: pnpm install / yarn install
```

### Environment Configuration

Create `.env.development` for local development:

```bash
# Base path for the application
VITE_BASE_PATH=/

# API endpoints (dynamic port, injected by Electron main process)
# In development mode, actual port is obtained via preload script
# VITE_API_BASE is set dynamically at runtime
```

Create `.env.production` for production build:

```bash
# Base path for Nginx deployment
VITE_BASE_PATH=/PathLab/

# API endpoints (proxied through Nginx)
VITE_API_BASE=/PathLab/api
VITE_AI_BASE=/PathLab/api/ai
VITE_PREPROCESSING_BASE=/PathLab/preprocessing
```

### Running Development Server

```bash
npm run dev
```

- Opens at: `http://127.0.0.1:5173`
- Hot Module Replacement (HMR) enabled
- CORS already configured on backend services

### Building for Production

```bash
npm run build
```

- Output: `dist/` directory
- Optimized and minified assets
- Ready for Nginx deployment at `/PathLab/`

### Production Deployment

The built frontend is served by Nginx with the following configuration:

```nginx
location /PathLab/ {
    alias /path/to/dist/;
    try_files $uri $uri/ /PathLab/index.html;
}

location /PathLab/api/ {
    # Port is dynamically allocated, configure to actual running port
    proxy_pass http://127.0.0.1:$PORT/;
}
```

## UI/UX Design

### Layout System

- **Responsive Sidebar**: Collapsible navigation (desktop) / drawer (mobile)
- **Header**: User info and breadcrumbs
- **Main Content**: Page-specific content area
- **Full-Screen Mode**: Available for WSI viewer

### Color Scheme

- **Primary**: Blue gradient (`from-blue-500 to-blue-600`)
- **Secondary**: Purple gradient (`from-purple-500 to-purple-600`)
- **Accent**: Teal (`teal-500`)
- **Neutral**: Gray scale for text and backgrounds

### Component Library

All components use Tailwind CSS utility classes for consistent styling:

- Buttons: `bg-primary-500 hover:bg-primary-600 text-white rounded-lg`
- Cards: `bg-white rounded-lg shadow-sm border border-gray-200`
- Inputs: `border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500`

## Data Flow

### WSI Viewing Flow

```
User navigates to /wsi/{wsi_id}
  ↓
WSIViewerPage fetches metadata from Gateway
  ↓
WSIViewer component initializes OpenSeadragon
  ↓
OpenSeadragon requests DZI descriptor from Preprocessing Service
  ↓
OpenSeadragon requests tiles as user pans/zooms
  ↓
Preprocessing Service generates tiles on-demand (cached)
```

### AI Analysis Flow

```
User submits analysis request
  ↓
Frontend calls Gateway /tasks/wsi_classification
  ↓
Gateway forwards to AI Service
  ↓
AI Service creates task and returns task_id
  ↓
Frontend polls /tasks/{task_id} for status
  ↓
When complete, fetch results from /results/{wsi_id}
  ↓
Display prediction and probabilities
```

### Chat Flow

```
User sends message
  ↓
Frontend calls Gateway /chat with message history
  ↓
Gateway streams LLM response (SSE/chunked transfer)
  ↓
Frontend updates UI incrementally as chunks arrive
  ↓
Parse response for task parameters (if applicable)
  ↓
Offer to create task or navigate to setup page
```

## Configuration

### Vite Configuration (`vite.config.ts`)

- **Base Path**: Configurable via `VITE_BASE_PATH` env variable
- **Dev Server**: Runs on `0.0.0.0:5173` for network access
- **Proxy**: WSI tile requests proxied to Preprocessing service in dev mode
- **File System**: Allows serving files from `uploads/` directory

### TypeScript Configuration

- **Target**: ES2020
- **Module**: ESNext
- **JSX**: React
- **Strict Mode**: Enabled
- **Path Aliases**: Not configured (uses relative imports)

## Testing (Planned)

Currently no automated tests. Recommended setup:

- **Unit Tests**: Vitest + React Testing Library
- **E2E Tests**: Playwright or Cypress
- **Component Tests**: Storybook

## Known Limitations

1. **Real-time Updates**: Task status requires polling
   - **Solution**: Implement WebSocket for live updates

2. **Error Handling**: Basic error messages
   - **Solution**: Add toast notifications and detailed error pages

3. **Accessibility**: Limited ARIA labels and keyboard navigation
   - **Solution**: Audit with axe-core and add proper semantics

## Future Enhancements

### Phase 1 (Current)
- ✅ Basic WSI viewer
- ✅ AI chat interface
- ✅ Task submission
- ✅ Results display

### Phase 2 (Partially Complete)
- [ ] Multi-user collaboration features
- [ ] Annotation tools (drawing, measurements)
- ✅ Advanced visualization (heatmaps, overlays)
- [ ] Batch analysis support
- ✅ Export functionality (PDF reports, CSV)

### Phase 3 (Future)
- [ ] Real-time collaboration (WebSocket)
- [ ] Mobile app (React Native)
- [ ] Offline mode (PWA)
- [ ] Plugin system for custom tools
- [ ] Integration with PACS/DICOM systems

## References

- [React Documentation](https://react.dev/)
- [Vite Documentation](https://vitejs.dev/)
- [OpenSeadragon Documentation](https://openseadragon.github.io/)
- [Tailwind CSS Documentation](https://tailwindcss.com/)
- [React Router Documentation](https://reactrouter.com/)

## Contributing

1. Follow existing code style (TypeScript + functional components)
2. Use Tailwind CSS for styling (avoid inline styles)
3. Keep components small and focused
4. Add comments for complex logic
5. Test manually before committing

## License

See root repository LICENSE file.

