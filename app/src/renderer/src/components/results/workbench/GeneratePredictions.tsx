import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight, CheckCircle2, Loader2, X } from "lucide-react";
import {
  resultGet,
  type Page,
} from "../../../api/resultWorkbench";
import { startExternalValidation } from "../../../api/analysis";
import {
  startBatchInference,
  startIndependentInference,
  type IndependentInferenceWSI,
} from "../../../api/batchInference";
import { useDebounce } from "../../../lib/hooks/useDebounce";
import { Button } from "../../ui/button";
import { Input } from "../../ui/input";
import { Select } from "../../ui/select";
import { Checkbox } from "../../ui/checkbox";
import { ModalShell } from "../../ui/modal-shell";
import { SegmentedControl } from "../../ui/workspace-primitives";
import { useResultText } from "./text";

interface Model {
  model_id: string;
  model_name: string;
  task_id: string;
  task_type: string;
  classes: string[];
}
interface Dataset {
  dataset_id: string;
  name: string;
  count: number;
  compatible: boolean;
  reason: string | null;
}

export default function GeneratePredictions({
  onClose,
  scopeKey,
  initialMode = "external",
  modelId = "",
}: {
  onClose: () => void;
  scopeKey: string;
  initialMode?: string;
  modelId?: string;
}) {
  const { text, reason } = useResultText();
  const navigate = useNavigate();
  const [mode, setMode] = useState(initialMode);
  const [model, setModel] = useState(modelId);
  const [modelQuery, setModelQuery] = useState("");
  const search = useDebounce(modelQuery, 250);
  const [dataQuery, setDataQuery] = useState("");
  const dataSearch = useDebounce(dataQuery, 250);
  const [modelOffset, setModelOffset] = useState(0);
  const [dataOffset, setDataOffset] = useState(0);
  const [dataset, setDataset] = useState("");
  const [selectedImages, setSelectedImages] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [taskId, setTaskId] = useState("");
  const models = useQuery({
    queryKey: ["result-models", scopeKey, search, modelOffset],
    queryFn: ({ signal }) =>
      resultGet<Page<Model>>(
        "/models",
        { query: search, offset: modelOffset },
        signal,
      ),
  });
  const modelDetail = useQuery({
    queryKey: ["result-model", scopeKey, model],
    queryFn: ({ signal }) =>
      resultGet<Model>("/model", { model_id: model }, signal),
    enabled: !!model,
  });
  const selectedModel = modelDetail.data;
  const datasets = useQuery({
    queryKey: [
      "result-datasets",
      scopeKey,
      model,
      dataOffset,
      mode,
      dataSearch,
    ],
    queryFn: ({ signal }) =>
      resultGet<Page<Dataset>>(
        "/datasets",
        { model_id: model, offset: dataOffset, mode, query: dataSearch },
        signal,
      ),
    enabled: !!model && ["external", "inference"].includes(mode),
  });
  const images = useQuery({
    queryKey: [
      "result-uploaded-images",
      scopeKey,
      model,
      dataOffset,
      dataSearch,
    ],
    queryFn: ({ signal }) =>
      resultGet<Page<IndependentInferenceWSI>>(
        "/images",
        { model_id: model, offset: dataOffset, query: dataSearch },
        signal,
      ),
    enabled: mode === "uploads" && !!selectedModel,
  });
  const modelOptions = [
    ...(selectedModel &&
    !models.data?.items.some((item) => item.model_id === model)
      ? [selectedModel]
      : []),
    ...(models.data?.items || []),
  ];
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      let id: string;
      if (mode === "external")
        id = (await startExternalValidation(model, dataset)).task_id;
      else if (mode === "inference" && selectedModel)
        id = (
          await startBatchInference({
            model_task_id: selectedModel.task_id,
            model_id: model,
            dataset_id: dataset,
          })
        ).task_id;
      else
        id = (
          await startIndependentInference({
            model_id: model,
            wsi_ids: selectedImages,
          })
        ).task_id;
      setTaskId(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const pagination = (
    offset: number,
    step: number,
    more: boolean,
    change: (value: number) => void,
  ) => (
    <div className="flex items-center justify-end gap-2">
      <Button
        size="sm"
        variant="ghost"
        disabled={!offset}
        onClick={() => change(offset - step)}
      >
        {text("previous")}
      </Button>
      <span className="text-xs text-slate-400">
        {text("pageNumber", { number: offset / step + 1 })}
      </span>
      <Button
        size="sm"
        variant="ghost"
        disabled={!more}
        onClick={() => change(offset + step)}
      >
        {text("next")}
      </Button>
    </div>
  );
  return (
    <ModalShell
      isOpen
      onClose={onClose}
      maxWidth="xl"
      title={text("generate")}
      className="!max-w-2xl"
    >
      <header className="border-b border-[color:var(--surface-border)] px-5 py-5 sm:px-7">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight text-slate-950">
              {text("generate")}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {text("evaluationHint")}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label={text("close")}
            onClick={onClose}
          >
            <X size={18} />
          </Button>
        </div>
      </header>
      {taskId ? (
        <div className="space-y-4 p-7 text-center">
          <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-600" />
          <p className="text-sm leading-6 text-slate-600">
            {text("submitted")}
          </p>
          <Button onClick={() => navigate(`/task/${taskId}`)}>
            {text("viewTask")}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      ) : (
        <>
          <div className="space-y-6 px-5 py-6 sm:px-7">
            <section>
              <h3 className="mb-3 text-sm font-semibold">
                {text("evaluationMode")}
              </h3>
              <div className="overflow-x-auto pb-1">
                <SegmentedControl
                  value={mode}
                  onChange={(value) => {
                    setMode(value);
                    setDataset("");
                    setDataOffset(0);
                    setSelectedImages([]);
                  }}
                  options={(
                    [
                      "external",
                      "inference",
                      "uploads",
                    ] as ("external" | "inference" | "uploads")[]
                  ).map((value) => ({ value, label: text(value) }))}
                  className="w-max min-w-full"
                />
              </div>
              <p className="mt-3 text-xs leading-6 text-slate-500">
                {text(
                  `${mode}Hint` as
                    | "externalHint"
                    | "inferenceHint"
                    | "uploadsHint"
                )}
              </p>
            </section>
            {(
              <>
                <section className="space-y-3">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs text-slate-500">
                      1
                    </span>
                    {text("chooseModel")}
                  </h3>
                  <Input
                    placeholder={text("searchModel")}
                    value={modelQuery}
                    onChange={(event) => {
                      setModelQuery(event.target.value);
                      setModelOffset(0);
                    }}
                  />
                  <Select
                    ariaLabel={text("model")}
                    placeholder={
                      models.isLoading ? text("loading") : text("chooseModel")
                    }
                    value={model}
                    options={modelOptions.map((item) => ({
                      value: item.model_id,
                      label: item.model_name,
                    }))}
                    onChange={(value) => {
                      setModel(value);
                      setDataset("");
                      setSelectedImages([]);
                      setDataOffset(0);
                    }}
                  />
                  {pagination(
                    modelOffset,
                    20,
                    !!models.data?.has_more,
                    setModelOffset,
                  )}
                </section>
                <section className="space-y-3 border-t border-[color:var(--surface-border)] pt-5">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs text-slate-500">
                      2
                    </span>
                    {text("chooseData")}
                  </h3>
                  <Input
                    placeholder={text("searchDataset")}
                    value={dataQuery}
                    disabled={!model}
                    onChange={(event) => {
                      setDataQuery(event.target.value);
                      setDataOffset(0);
                    }}
                  />
                  {mode === "uploads" ? (
                    <>
                      <div className="max-h-60 space-y-1 overflow-y-auto rounded-2xl bg-[color:var(--surface-muted)] p-2">
                        {images.isLoading && model ? (
                          <p className="p-3 text-xs text-slate-500">
                            {text("loading")}
                          </p>
                        ) : images.data?.items.length ? (
                          images.data.items.map((item) => (
                            <div
                              key={item.wsi_id}
                              className="flex items-center gap-3 rounded-xl px-3 py-2.5"
                            >
                              <Checkbox
                                aria-label={
                                  item.original_filename || item.wsi_id
                                }
                                disabled={
                                  item.availability?.status === "unavailable"
                                }
                                checked={selectedImages.includes(item.wsi_id)}
                                onCheckedChange={(checked) =>
                                  setSelectedImages((value) =>
                                    checked
                                      ? [...value, item.wsi_id]
                                      : value.filter(
                                          (id) => id !== item.wsi_id,
                                        ),
                                  )
                                }
                              />
                              <span className="min-w-0 truncate text-xs text-slate-600">
                                {item.original_filename || item.wsi_id}
                              </span>
                            </div>
                          ))
                        ) : (
                          <p className="p-3 text-xs text-slate-500">
                            {model ? text("noOptions") : text("modelFirst")}
                          </p>
                        )}
                      </div>
                      {pagination(
                        dataOffset,
                        50,
                        !!images.data?.has_more,
                        setDataOffset,
                      )}
                    </>
                  ) : (
                    <>
                      <Select
                        ariaLabel={text("dataset")}
                        value={dataset}
                        disabled={!model || datasets.isLoading}
                        placeholder={
                          !model
                            ? text("modelFirst")
                            : datasets.isLoading
                              ? text("loading")
                              : text("chooseData")
                        }
                        options={(datasets.data?.items || []).map((item) => ({
                          value: item.dataset_id,
                          label: `${item.name} · ${item.count}${item.reason ? ` · ${reason(item.reason)}` : ""}`,
                          disabled: !item.compatible,
                        }))}
                        onChange={setDataset}
                      />
                      {pagination(
                        dataOffset,
                        20,
                        !!datasets.data?.has_more,
                        setDataOffset,
                      )}
                    </>
                  )}
                </section>
              </>
            )}
            {(error ||
              models.error ||
              datasets.error ||
              images.error ||
              modelDetail.error) && (
              <p
                role="alert"
                className="rounded-xl bg-red-50 p-3 text-sm text-red-600"
              >
                {error ||
                  String(
                    models.error ||
                      datasets.error ||
                      images.error ||
                      modelDetail.error,
                  )}
              </p>
            )}
          </div>
          <footer className="flex flex-col gap-4 border-t border-[color:var(--surface-border)] bg-[color:var(--surface-muted)] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
            <p className="max-w-sm text-xs leading-5 text-slate-500">
              {text("evaluationReady")}
            </p>
            <Button
              disabled={
                busy ||
                (!selectedModel ||
                    (mode === "uploads" ? !selectedImages.length : !dataset))
              }
              onClick={() => void submit()}
              className="shrink-0"
            >
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {text(mode === "external" ? "startEvaluation" : "startInference")}
            </Button>
          </footer>
        </>
      )}
    </ModalShell>
  );
}
