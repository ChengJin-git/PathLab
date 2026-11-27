import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Loader2, MessageCircleQuestion, Send, X} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {useTranslation} from 'react-i18next';
import {askResearchQuestion, type ResearchQuestionTurn} from '../../api/workbench';
import {Button} from '../ui/button';
import {useWorkbenchText} from '../chat/workbenchText';

export default function ResearchSideQuestion({sessionId, selection, onClose}: {
  sessionId: string;
  selection: {sequence?: number; version: number} | null;
  onClose: () => void;
}) {
  const text = useWorkbenchText();
  const {i18n} = useTranslation();
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<ResearchQuestionTurn[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    request.current?.abort(); request.current = null;
    setHistory([]); setError(''); setBusy(false); setInput('');
    if(selection) textarea.current?.focus({preventScroll:true});
    return () => {request.current?.abort();};
  }, [sessionId, selection?.sequence, selection?.version]);
  if(!selection) return null;
  async function send(event: React.FormEvent) {
    event.preventDefault();
    if(!input.trim() || busy) return;
    const controller = new AbortController(); request.current = controller;
    const question = input.trim(); setBusy(true);setError('');
    try {
      const language = /zh-(HK|TW|Hant)/i.test(i18n.language) ? 'zh-HK' : i18n.language.startsWith('zh') ? 'zh-CN' : 'en-US';
      const response = await askResearchQuestion(sessionId, {question, event_seq:selection?.sequence,
        history:history.slice(-6).map(turn=>({...turn,content:turn.content.slice(0,5000)})), language}, controller.signal);
      if(controller.signal.aborted) return;
      setHistory(previous=>[...previous,{role:'user',content:question},{role:'assistant',content:response.answer}].slice(-12) as ResearchQuestionTurn[]);
      setInput('');
    } catch(e) {if(!controller.signal.aborted) setError((e as Error).message);}
    finally {if(request.current===controller){request.current=null;setBusy(false);}}
  }
  return createPortal(<section role="dialog" aria-label={text('sideQuestion')} aria-modal="false"
    className="fixed bottom-4 right-4 z-[75] flex max-h-[min(80vh,720px)] w-[min(440px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
    onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();onClose();}}}>
    <header className="flex items-center gap-2 border-b px-4 py-3"><MessageCircleQuestion size={17}/>
      <h2 className="flex-1 text-sm font-semibold">{text('sideQuestion')}</h2>
      <Button type="button" variant="ghost" size="icon" aria-label={text('close')} onClick={onClose}><X size={16}/></Button>
    </header>
    <div className="border-b bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
      {text('sideQuestionHint')}
      {selection.sequence && <p className="mt-1 font-medium">{text('sideQuestionSelected').replace('{number}',String(selection.sequence))}</p>}
    </div>
    <div className="min-h-20 flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
      {history.map((turn,index)=><article key={index} className={turn.role==='user'?'rounded-lg bg-slate-100 p-3 text-sm':'prose prose-sm max-w-none break-words'}>
        {turn.role==='user'?turn.content:<ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown>}
      </article>)}
      {!history.length && <p className="text-sm text-slate-500">{text('sideQuestionExample')}</p>}
      {busy && <p role="status" className="flex items-center gap-2 text-xs text-slate-500"><Loader2 size={14} className="animate-spin"/>{text('sideQuestionThinking')}</p>}
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
    <form className="space-y-2 border-t p-3" onSubmit={event=>void send(event)}>
      <textarea ref={textarea} aria-label={text('sideQuestionInput')} value={input} onChange={event=>setInput(event.target.value)}
        maxLength={4000} rows={3} placeholder={text('sideQuestionExample')} className="w-full resize-y rounded-lg border p-2 text-sm outline-none focus:ring-2 focus:ring-primary-300"/>
      <div className="flex justify-end"><Button type="submit" size="sm" disabled={busy||!input.trim()} className="gap-2"><Send size={14}/>{text('sideQuestionSend')}</Button></div>
    </form>
  </section>,document.body);
}
