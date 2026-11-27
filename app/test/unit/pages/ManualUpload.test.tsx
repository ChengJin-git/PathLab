import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
  act,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import UploadPage from "@renderer/pages/UploadPage";
import * as api from "@renderer/api";
import * as catalog from '@renderer/api/datasetCatalog';
import * as upload from "@renderer/components/upload";
import * as tasks from "@renderer/contexts/BackgroundTaskContext";
import * as auth from "@renderer/contexts/AuthContext";
import * as toast from "@renderer/contexts/ToastContext";
import { TooltipProvider } from "@renderer/components/ui/tooltip";
import i18n from "@renderer/i18n";
import ExcelJS from 'exceljs';

const submit = vi.fn();
beforeEach(async () => {
  vi.restoreAllMocks();
  submit.mockReset();
  sessionStorage.clear();
  await i18n.changeLanguage("en-US");
  vi.spyOn(auth, "useAuth").mockReturnValue({
    user: { id: "owner" },
    isAdmin: false,
  } as ReturnType<typeof auth.useAuth>);
  vi.spyOn(toast, "useToast").mockReturnValue({
    error: vi.fn(),
    warning: vi.fn(),
  } as unknown as ReturnType<typeof toast.useToast>);
  vi.spyOn(tasks, "useBackgroundTask").mockReturnValue({
    addUploadTask: submit,
  } as unknown as ReturnType<typeof tasks.useBackgroundTask>);
  vi.spyOn(api, "fetchDatasets").mockResolvedValue({ items: [], total: 0 });
  vi.spyOn(catalog,'createDataset').mockImplementation(async draft=>({...draft,dataset_id:'created',revision:1,source_organ:draft.source_organ||null}));
  vi.spyOn(api, "checkDuplicateFilenames").mockResolvedValue({
    duplicates: [],
    new: [],
  });
});
async function setup(count = 2, mode = "classification", level = "file") {
  const files = Array.from({ length: count }, (_, i) => ({
    key: `f${i}`,
    name: `image-${i}.svs`,
    type: "standard" as const,
    file: new File(["x"], `image-${i}.svs`),
  }));
  vi.spyOn(upload, "collectItemsFromDataTransfer").mockResolvedValue({
    items: files,
    orphanFolders: [],
    orphanDtFiles: new Map(),
    unsupportedFileNames: [],
    jsonFiles: [],
  });
  const view = render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/upload",
            state: {
              datasetName: "New cohort",
              uploadMode: mode,
              dataLevel: level,
            },
          },
        ]}
      >
        <TooltipProvider>
          <UploadPage />
        </TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("New cohort");
  const picker = view.container.querySelector("input[type=file]")!;
  fireEvent.change(picker, { target: { files: [files[0].file] } });
  await waitFor(() =>
    expect(view.container.querySelectorAll("tbody tr").length).toBe(
      Math.min(count, 10),
    ),
  );
  return view;
}
async function csv(
  container: HTMLElement,
  text: string,
  name = "metadata.csv",
) {
  const input = container.querySelector(
    'input[accept=".csv,.xlsx,.xls"]',
  ) as HTMLInputElement;
  if (!input) {
    fireEvent.click(screen.getByText(/Dataset Metadata Configuration/i));
  }
  const field = container.querySelector(
    'input[accept=".csv,.xlsx,.xls"]',
  ) as HTMLInputElement;
  await userEvent.upload(field, new File([text], name, { type: "text/csv" }));
  await screen.findByText(name);
}
it("preserves CSV patient IDs and split, and does not reread the CSV on submission", async () => {
  submit.mockResolvedValue("job");
  const view = await setup(2, "classification", "case");
  await csv(
    view.container,
    "filename,label,case_id,split\nimage-0.svs,tumor,P-01,train\nimage-1.svs,tumor,P-01,train\n",
  );
  expect(view.container.querySelectorAll('input[value="P-01"]')).toHaveLength(
    2,
  );
  await userEvent.click(screen.getByRole("button", { name: /Register All/i }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0].map((item: any) => item.metadata)).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        case_id: "P-01",
        split: "train",
        label: "tumor",
      }),
    ]),
  );
});
it("blocks leakage across case splits and invalid survival numbers before queuing", async () => {
  const view = await setup(2, "survival", "case");
  await csv(
    view.container,
    "filename,event_time,event_status,case_id,split\nimage-0.svs,12,0,P-01,train\nimage-1.svs,24,1,P-01,test\n",
  );
  await userEvent.click(screen.getByRole("button", { name: /Register All/i }));
  expect(
    await screen.findByText(/Keep every case in a single split/),
  ).toBeVisible();
  expect(submit).not.toHaveBeenCalled();
});
it('converts real XLSX once, keeps blank columns and preserves zero-valued survival data',async()=>{
  submit.mockResolvedValue('job')
  const view=await setup(2,'survival','case')
  const workbook=new ExcelJS.Workbook(),sheet=workbook.addWorksheet('Metadata')
  sheet.addRow(['filename','event_time','event_status','case_id','split','age'])
  sheet.addRow(['image-0.svs',0,0,'P-01','train'])
  sheet.addRow(['image-1.svs',12,1,'P-02','val'])
  const bytes=await workbook.xlsx.writeBuffer()
  const file=new File([new Uint8Array(bytes as ArrayBuffer)],'cases.xlsx',{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
  Object.defineProperty(file,'arrayBuffer',{value:async()=>bytes})
  fireEvent.click(screen.getByText(/Dataset Metadata Configuration/i))
  await userEvent.upload(view.container.querySelector('input[accept=".csv,.xlsx,.xls"]') as HTMLInputElement,file)
  await screen.findByText('cases.csv')
  await userEvent.click(screen.getByRole('button',{name:/Register All/i}))
  await waitFor(()=>expect(submit).toHaveBeenCalledTimes(1))
  expect(submit.mock.calls[0][0][0].metadata).toMatchObject({case_id:'P-01',event_time:0,event_status:0,split:'train'})
})
it('blocks malformed metadata replacement and allows the user to correct it without losing files',async()=>{
  const view=await setup()
  await csv(view.container,'filename,label\nimage-0.svs,tumor\nimage-1.svs,normal\n')
  await userEvent.click(screen.getByRole('button',{name:'Remove file Sample metadata (CSV)'}))
  await userEvent.upload(view.container.querySelector('input[accept=".csv,.xlsx,.xls"]') as HTMLInputElement,new File(['wrong,header\nx,y'],'bad.csv',{type:'text/csv'}))
  await screen.findByText(/Missing required column: filename/i)
  await userEvent.click(screen.getByRole('button',{name:/Register All/i}))
  expect(submit).not.toHaveBeenCalled()
  expect(view.container.querySelectorAll('tbody tr')).toHaveLength(2)
})
it("keeps only one page mounted for ten thousand files and selects the page independently", async () => {
  const view = await setup(10000);
  expect(view.container.querySelectorAll("tbody tr")).toHaveLength(10);
  await userEvent.click(screen.getByRole("button", { name: "Files per page" }));
  await userEvent.click(screen.getByRole("option", { name: "50" }));
  expect(view.container.querySelectorAll("tbody tr")).toHaveLength(50);
  fireEvent.change(screen.getByRole("spinbutton", { name: "Go to page" }), {
    target: { value: "200" },
  });
  fireEvent.blur(screen.getByRole("spinbutton", { name: "Go to page" }));
  expect(await screen.findByText("image-9999.svs")).toBeVisible();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Select this page" }),
  );
  expect(
    within(view.container.querySelector("tbody")!).getAllByRole("checkbox", {
      checked: true,
    }),
  ).toHaveLength(50);
  expect(api.fetchDatasets).toHaveBeenCalledWith(
    undefined,
    expect.objectContaining({ page_size: 20 }),
  );
  expect(api.checkDuplicateFilenames).not.toHaveBeenCalled();
});

it.each([false, true])('restricts existing upload choices and uploader display for admin=%s', async (isAdmin) => {
  vi.mocked(auth.useAuth).mockReturnValue({ user: { id: 'owner' }, isAdmin } as ReturnType<typeof auth.useAuth>);
  const datasets = [
    { dataset_id: 'own', dataset_name: 'My patches', user_id: 'owner', username: 'Owner Name', data_type: 'patch',task_types:['patch_classification'],aggregation_level:'file',file_count:1,metadata:{},revision:1 },
    { dataset_id: 'other', dataset_name: 'Other slides', user_id: 'other-owner', username: 'Other Name', data_type: 'wsi',task_types:['wsi_classification'],aggregation_level:'file',file_count:1,metadata:{},revision:1 },
  ] as api.DatasetSummary[];
  vi.mocked(api.fetchDatasets).mockResolvedValue({ items: datasets, total: 2 });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/upload']}>
        <TooltipProvider><UploadPage /></TooltipProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const own = await screen.findByRole('button', { name: /My patches/ });
  expect(own).toHaveTextContent('Image patches');
  expect(own.textContent?.includes('Owner Name')).toBe(isAdmin);
  expect(screen.queryByRole('button', { name: /Other slides/ }) !== null).toBe(isAdmin);
  if (isAdmin) expect(screen.getByRole('button', { name: /Other slides/ })).toHaveTextContent('Whole-slide images · Other Name');
  expect(api.fetchDatasets).toHaveBeenCalledWith(undefined, expect.objectContaining({ purpose: 'upload' }));
  vi.spyOn(api, 'fetchDatasetSummary').mockResolvedValue(datasets[0]);
  await userEvent.click(own);
  await waitFor(() => expect(api.fetchDatasetSummary).toHaveBeenCalledWith('own', 'upload'));
});
