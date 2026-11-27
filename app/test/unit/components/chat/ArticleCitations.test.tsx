import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AssistantMessage, { findReferenceCardForCitation } from "@renderer/components/chat/AssistantMessage";
import { parseAllReferenceCards } from "@renderer/components/chat/ReferenceCard";
import type { CitationSource } from "@renderer/api/chat";

vi.mock('react-i18next', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-i18next')>(),
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }),
}));
afterEach(cleanup);

const sources: CitationSource[] = [{ source_id: 'gpfm', source_index: 1, title: 'GPFM', url: 'https://www.nature.com/articles/gpfm', pages: { '2': 'Classification results', '3': 'Survival results', '8': 'Distillation ablation', '10': 'Unified knowledge distillation' } }];
const reference = '[REFERENCE]\ntitle: GPFM\nurl: https://www.nature.com/articles/gpfm\nsource_id: gpfm\nsource_index: 1\n[/REFERENCE]';
const contexts = '[CITATION_CONTEXTS]' + JSON.stringify({
  '1-p.2–3': { page: 2, context: 'Measured results', source_id: 'gpfm' },
  '1-p.8': { page: 8, context: 'Ablation results', source_id: 'gpfm' },
  '1-p.10': { page: 10, context: 'Methods', source_id: 'gpfm' },
}) + '[/CITATION_CONTEXTS]';
const noop = () => {};
function message(content: string, isStreaming = true, citationSources = sources) {
  return <MemoryRouter><AssistantMessage content={content} messageId="fixture" isStreaming={isStreaming} isLoading={isStreaming}
    onOptionSelect={noop} onTaskSubmitSuccess={noop} onInternalAnalysisSubmitSuccess={noop} onTaskSubmitError={noop}
    onTaskHistoryDataLoaded={noop} onQuickAnalysisDataLoaded={noop} onHelpfulnessFeedback={noop} onToast={noop}
    onRegistrationSuccess={noop} onMetadataUploadSuccess={noop} searchArtifacts={{citationSources}} /></MemoryRouter>;
}

it("resolves source IDs and explicit indices independently of display order", () => {
  const cards = parseAllReferenceCards(
    "[REFERENCE]\ntitle: BERT\nurl: https://arxiv.org/abs/1810.04805\nsource_id: bert\nsource_index: 2\n[/REFERENCE]\n[REFERENCE]\ntitle: Attention\nurl: https://arxiv.org/abs/1706.03762\nsource_id: attention\nsource_index: 1\n[/REFERENCE]",
  );
  expect(findReferenceCardForCitation(cards, "1-p.3", "attention")?.title).toBe(
    "Attention",
  );
  expect(findReferenceCardForCitation(cards, "2-p.3", "bert")?.title).toBe(
    "BERT",
  );
  expect(findReferenceCardForCitation(cards, "1-bare")?.title).toBe(
    "Attention",
  );
  expect(findReferenceCardForCitation(cards, "3-p.3")).toBeUndefined();
  expect(
    findReferenceCardForCitation(cards, "1-p.3", "missing"),
  ).toBeUndefined();
});

it('renders numbered page citations before final context blocks and keeps numbers on completion/reload', () => {
  const body = '结果[1, p.2–3]消融[1,p.8]方法[1, p.10]再次消融[1,p.8]';
  const view = render(message(body));
  const badges = () => Array.from(view.container.querySelectorAll('[data-citation-index]'));
  expect(badges().map(b => b.textContent)).toEqual(['1', '2', '3', '2']);
  expect(badges().every(b => b.getAttribute('data-source-index') === '1')).toBe(true);
  expect(view.container.textContent).not.toContain('[1');
  fireEvent.mouseEnter(badges()[1]);
  expect(view.getByText('📄 Page 8')).toBeInTheDocument();
  expect(view.getByText('"Distillation ablation"')).toBeInTheDocument();
  view.rerender(message(body + contexts + reference, false, []));
  expect(badges().map(b => b.textContent)).toEqual(['1', '2', '3', '2']);
  expect(view.container.textContent).not.toContain('CITATION_CONTEXTS');
});

it('handles CJK punctuation and incomplete bold while streaming without changing the stored Markdown', () => {
  const prefix = '**最稳妥的结论是：GPFM 提供了均衡的表征方案。**在论文中';
  const view = render(message(prefix));
  expect(view.container.querySelector('strong')).toHaveTextContent('最稳妥的结论是：GPFM 提供了均衡的表征方案。');
  expect(view.container.textContent).not.toContain('**');
  view.rerender(message('正文 **蒸馏的对象不只是分类答案'));
  expect(view.container.querySelector('strong')).toHaveTextContent('蒸馏的对象不只是分类答案');
  expect(view.container.textContent).not.toContain('**');
  view.rerender(message(prefix, false));
  expect(view.container.querySelector('strong')).toHaveTextContent('最稳妥的结论');
  view.rerender(message('**'));
  expect(view.container.textContent).not.toContain('**');
});

it('does not flash citation syntax at any chunk boundary', () => {
  const view = render(message('实验证据'));
  const citation = '[1, p.8]';
  for (let i = 1; i <= citation.length; i++) {
    view.rerender(message('实验证据' + citation.slice(0, i)));
    expect(view.container.querySelector('.prose')?.textContent).not.toMatch(/\[|p\./);
  }
  expect(view.container.querySelector('[data-citation-index]')).toHaveTextContent('1');
});

it('numbers bare and page references in appearance order across multiple sources', () => {
  const second = { source_id: 'uni', source_index: 2, title: 'UNI', url: 'https://example.org/uni', pages: {'3':'UNI result'} };
  const view = render(message('UNI[2] GPFM[1,p.8] Compare[1,2] UNI page[2,p.3]', true, [...sources, second]));
  const badges = Array.from(view.container.querySelectorAll('[data-citation-index]'));
  expect(badges.map(b => b.textContent)).toEqual(['1','2','3','1','4']);
  expect(badges.map(b => b.getAttribute('data-source-id'))).toEqual(['uni','gpfm','gpfm','uni','uni']);
});

it('preserves code, actual links and unknown pages instead of inventing citation evidence', () => {
  const body = '`[1,p.8]`\n\n```txt\n**literal** [1,p.10]\n```\n\n[1,p.8](https://example.org) unknown [1,p.99] missing [9,p.8] actual[1,p.8]';
  const view = render(message(body, false));
  expect(view.container.querySelectorAll('[data-citation-index]')).toHaveLength(1);
  expect(view.getByRole('link', {name: /1,p.8/})).toHaveAttribute('href','https://example.org');
  expect(view.container.querySelector('pre')).toHaveTextContent('**literal** [1,p.10]');
  expect(view.container.textContent).toContain('[1,p.99]');
  expect(view.container.textContent).toContain('[9,p.8]');
  view.rerender(message('code `[1, p.'));
  expect(view.container.querySelector('code')).toHaveTextContent('[1, p.');
});
