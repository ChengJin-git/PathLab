import {render,screen,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {InspectionProgress} from '@renderer/components/settings/storage/InspectionProgress';
vi.mock('react-i18next',()=>({useTranslation:()=>({i18n:{language:'zh-CN'}})}));
afterEach(cleanup);
it('shows actual counts and cancel without exposing request-deduplication details',()=>{
 render(<InspectionProgress value={{kind:'external-health',status:'running',stage:'external-health',processed:50,total:200,reused:true}} onCancel={vi.fn()}/>);
 expect(screen.getByRole('progressbar')).toHaveAttribute('value','25');
 expect(screen.getByRole('status')).toHaveTextContent('50 / 200');
 expect(screen.getByRole('status')).not.toHaveTextContent(/复用|未重复|幂等/);
 expect(screen.getByRole('button',{name:'取消'})).toBeInTheDocument();
});
it('uses indeterminate progress until total is known',()=>{
 render(<InspectionProgress value={{kind:'external-health',status:'running',stage:'database',processed:20}}/>);
 expect(screen.getByRole('progressbar')).not.toHaveAttribute('value');
});
