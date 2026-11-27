import { lazy, Suspense, useEffect, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Download, Loader2, RefreshCw, X } from 'lucide-react';
import { downloadWorkbenchFile, referenceResearchPath, type ResourceItem, type FilePreview } from '../../api/workbench';
import { Button } from '../ui/button';
import { useWorkbenchText } from '../chat/workbenchText';

const FilePreviewContent = lazy(() => import('../chat/FilePreviewContent'));

export function researchFilePath(href: string | undefined, workspacePath?: string): string | undefined {
  if (!href || /^(?:[a-z]+:|\/\/|#)/i.test(href)) return;
  let path = href.split('#')[0];
  try { path = decodeURIComponent(path); } catch { return; }
  if (workspacePath && path.startsWith(workspacePath + '/')) path = path.slice(workspacePath.length + 1);
  if (path.startsWith('/') || path.split('/').includes('..')) return;
  return path.replace(/^\.\//, '') || undefined;
}

export default function ResearchFilePreview({ sessionId, path, workspaceId, onClose }: {
  sessionId: string;
  path: string;
  workspaceId?: string | null;
  onClose: () => void;
}) {
  const text = useWorkbenchText();
  const [file, setFile] = useState<ResourceItem & {preview?: FilePreview}>();
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFile(undefined);
    setError('');
    void referenceResearchPath(sessionId, path, controller.signal, true).then(item => {
      if (!controller.signal.aborted) setFile(item);
    }).catch(() => { if (!controller.signal.aborted) setError(text('previewUnavailable')); });
    return () => controller.abort();
  }, [sessionId, path, reload]);
  const loading = <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" />{text('loading')}</div>;
  return <Dialog.Root open onOpenChange={open => { if (!open) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-sm" />
      <Dialog.Content aria-describedby={undefined} className="fixed inset-2 z-50 flex min-h-0 flex-col overflow-hidden rounded-3xl border border-[color:var(--surface-border)] bg-[color:var(--surface-elevated)] shadow-[var(--shadow-elevated)] sm:inset-6 lg:inset-x-[6vw]">
        <header className="flex shrink-0 items-center gap-2 border-b border-[color:var(--surface-border)] px-4 py-3">
          <Dialog.Title className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-800">{file?.name || path.split('/').at(-1)}</Dialog.Title>
          <Button type="button" variant="ghost" size="icon" aria-label={text('reloadFile')} title={text('reloadFile')} onClick={() => setReload(value => value + 1)}><RefreshCw size={16} /></Button>
          <Button type="button" variant="ghost" size="icon" disabled={!file} aria-label={text('download')} title={text('download')} onClick={() => {
            if (file) void downloadWorkbenchFile(file, workspaceId).catch(() => setError(text('previewUnavailable')));
          }}><Download size={17} /></Button>
          <Dialog.Close asChild><Button type="button" variant="ghost" size="icon" aria-label={text('close')}><X size={18} /></Button></Dialog.Close>
        </header>
        {error && <p role="alert" className="p-4 text-sm text-red-700">{error}</p>}
        <div className="min-h-0 flex-1">
          {file ? <Suspense fallback={loading}><FilePreviewContent key={`${file.id}:${file.revision}`} file={file} initialPreview={file.preview} workspaceId={workspaceId} /></Suspense> : !error && loading}
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
