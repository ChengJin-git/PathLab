import React from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import ResearchSideQuestion from '@renderer/components/autoresearch/ResearchSideQuestion';
import ResearchTimeline from '@renderer/components/autoresearch/ResearchTimeline';
import {askResearchQuestion} from '@renderer/api/workbench';
import i18n from '@renderer/i18n';

vi.mock('@renderer/api/workbench',()=>({askResearchQuestion:vi.fn()}));
beforeEach(async()=>{await i18n.changeLanguage('en-US');vi.mocked(askResearchQuestion).mockReset();});
afterEach(cleanup);

it('asks about a selected historical update through the isolated endpoint and retains follow-up context',async()=>{
  vi.mocked(askResearchQuestion).mockResolvedValue({answer:'This is a paired comparison, not an independent test.',research_unchanged:true});
  render(<ResearchSideQuestion sessionId="research-a" selection={{sequence:123,version:1}} onClose={vi.fn()}/>);
  expect(screen.getByText(/not sent to the researcher/)).toBeVisible();
  fireEvent.change(screen.getByRole('textbox',{name:'Your side question'}),{target:{value:'Why was this control chosen?'}});
  fireEvent.click(screen.getByRole('button',{name:'Ask'}));
  expect(await screen.findByText('This is a paired comparison, not an independent test.')).toBeVisible();
  expect(askResearchQuestion).toHaveBeenCalledWith('research-a',expect.objectContaining({question:'Why was this control chosen?',event_seq:123,history:[]}),expect.any(AbortSignal));
  fireEvent.change(screen.getByRole('textbox'),{target:{value:'What does paired mean?'}});
  fireEvent.click(screen.getByRole('button',{name:'Ask'}));
  await waitFor(()=>expect(askResearchQuestion).toHaveBeenCalledTimes(2));
  expect(vi.mocked(askResearchQuestion).mock.calls[1][1].history).toHaveLength(2);
});

it('aborts only the question and ignores its late response when closed or changed',async()=>{
  let answer!:(value:any)=>void;
  vi.mocked(askResearchQuestion).mockImplementation(()=>new Promise(resolve=>{answer=resolve;}));
  const view=render(<ResearchSideQuestion sessionId="a" selection={{version:1}} onClose={vi.fn()}/>);
  fireEvent.change(screen.getByRole('textbox'),{target:{value:'Explain'}});
  fireEvent.click(screen.getByRole('button',{name:'Ask'}));
  const signal=vi.mocked(askResearchQuestion).mock.calls[0][2]!;
  view.rerender(<ResearchSideQuestion sessionId="b" selection={{version:2}} onClose={vi.fn()}/>);
  expect(signal.aborted).toBe(true);
  await act(async()=>answer({answer:'Stale private answer',research_unchanged:true}));
  expect(screen.queryByText('Stale private answer')).not.toBeInTheDocument();
});

it('exposes a question action at the historical record without a research command',()=>{
  const ask=vi.fn();
  render(<ResearchTimeline events={[{kind:'research_decision',seq:99,decision:{action:'keep',observation:'Measured AUC 0.8',interpretation:'Exploratory',next_action:'Repeat'}}]}
    running onAsk={ask} renderProse={value=><p>{value}</p>}/>);
  fireEvent.click(screen.getByRole('button',{name:'Ask about this step'}));
  expect(ask).toHaveBeenCalledWith(99);
});
