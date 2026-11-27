import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import FilePreviewContent from '@renderer/components/chat/FilePreviewContent';
import { previewWorkbenchFile, readWorkbenchMedia, readWorkbenchPage, type FilePreview } from '@renderer/api/workbench';
import i18n from '@renderer/i18n';

vi.mock('@renderer/api/workbench', () => ({ previewWorkbenchFile: vi.fn(), readWorkbenchMedia: vi.fn(), readWorkbenchPage: vi.fn() }));
const file = {kind: 'file' as const, id: 'deck', name: 'review.pptx', revision: 'v1'};
const preview = (kind: FilePreview['kind']): FilePreview => ({file_id: file.id, name: file.name, revision: '123:456', size: 456,
  kind, truncated: false, page_count: 2, page_width: 960, page_height: 540});
beforeEach(async () => {
  await i18n.changeLanguage('en-US');
  Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:preview')});
  Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: vi.fn()});
  vi.mocked(previewWorkbenchFile).mockReset();
  vi.mocked(readWorkbenchPage).mockReset().mockResolvedValue(new Blob(['page'], {type: 'image/png'}));
  vi.mocked(readWorkbenchMedia).mockReset().mockResolvedValue(new Blob(['media']));
});
afterEach(cleanup);

it.each(['slides', 'pdf', 'document'] as const)('opens %s with rendered pages, pagination and zoom', async kind => {
  vi.mocked(previewWorkbenchFile).mockResolvedValue(preview(kind));
  render(<FilePreviewContent file={file} workspaceId="scope" />);
  expect(await screen.findByRole('img', {name: /review.pptx: (Slide|Page) 1 of 2/})).toHaveAttribute('src', 'blob:preview');
  expect(readWorkbenchPage).toHaveBeenCalledWith('deck', 1, '123:456', 'scope', expect.any(AbortSignal));
  expect(readWorkbenchMedia).not.toHaveBeenCalled();
  expect(screen.getByRole('button', {name: 'Previous page'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
  expect(await screen.findByRole('img', {name: /review.pptx: (Slide|Page) 2 of 2/})).toBeVisible();
  expect(readWorkbenchPage).toHaveBeenLastCalledWith('deck', 2, '123:456', 'scope', expect.any(AbortSignal));
  expect(screen.getByRole('button', {name: 'Next page'})).toBeDisabled();
  // The previous page stays cached for immediate back navigation.
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name: 'Preview zoom'}));
  fireEvent.click(await screen.findByRole('option', {name: '150%'}));
  expect(screen.getByRole('img')).toHaveStyle({width: '1440px'});
  expect(readWorkbenchPage).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', {name: 'Previous page'}));
  expect(await screen.findByRole('img', {name: /review.pptx: (Slide|Page) 1 of 2/})).toBeVisible();
  expect(readWorkbenchPage).toHaveBeenCalledTimes(2);
});

it('uses an authorized supplied descriptor and first page without sequential requests', async () => {
  const data = {...preview('slides'), first_page: 'data:image/png;base64,cGFnZQ=='};
  render(<FilePreviewContent file={file} initialPreview={data} />);
  const image = screen.getByRole('img');
  expect(image).toHaveAttribute('src', data.first_page);
  expect(previewWorkbenchFile).not.toHaveBeenCalled();
  expect(readWorkbenchPage).not.toHaveBeenCalled();
  // Prefetch only after the visible page has loaded, never before first paint.
  fireEvent.load(image);
  await waitFor(() => expect(readWorkbenchPage).toHaveBeenCalledOnce());
  expect(readWorkbenchPage).toHaveBeenCalledWith('deck', 2, '123:456', undefined, expect.any(AbortSignal));
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole('button', {name: 'Next page'}));
  expect(await screen.findByRole('img', {name: /Slide 2 of 2/})).toBeVisible();
  expect(readWorkbenchPage).toHaveBeenCalledOnce();
});

it('aborts a previous page and ignores its late response', async () => {
  vi.mocked(previewWorkbenchFile).mockResolvedValue(preview('pdf'));
  let first!: (blob: Blob) => void;
  vi.mocked(readWorkbenchPage).mockImplementationOnce(() => new Promise(resolve => {first = resolve;}));
  const view = render(<FilePreviewContent file={file} />);
  fireEvent.click(await screen.findByRole('button', {name: 'Next page'}));
  expect(await screen.findByRole('img', {name: /Page 2 of 2/})).toBeVisible();
  expect(vi.mocked(readWorkbenchPage).mock.calls[0][4]?.aborted).toBe(true);
  await act(async () => { first(new Blob(['late page'])); });
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
});

it.each(['table', 'markdown', 'html', 'code', 'image', 'audio', 'video', 'unsupported'] as const)('routes %s to its dedicated preview', async kind => {
  vi.mocked(previewWorkbenchFile).mockResolvedValue({...preview(kind), content: '# Report', rows: [['Metric','Value'],['AUC','0.81']]});
  const view = render(<FilePreviewContent file={file} />);
  await waitFor(() => expect(view.container.querySelector(`[data-preview-kind="${kind}"]`)).not.toBeNull());
  const selector = {table:'table', markdown:'article', html:'iframe[sandbox=""]', code:'pre code', image:'img', audio:'audio[controls]', video:'video[controls]', unsupported:'p'}[kind];
  expect(view.container.querySelector(selector)).not.toBeNull();
  expect(readWorkbenchPage).not.toHaveBeenCalled();
});
