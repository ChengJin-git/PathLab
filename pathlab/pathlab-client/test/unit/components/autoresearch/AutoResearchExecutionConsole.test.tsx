import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AutoResearchExecutionConsole from '@renderer/components/autoresearch/AutoResearchExecutionConsole'
import i18n from '@renderer/i18n'
import type { AutoResearchEvent, AutoResearchSessionDetail } from '@renderer/types/autoresearch'

const events: AutoResearchEvent[] = [
  { kind: 'session', ts: 1000, status: 'running', stage: 'grounding', summary: 'Session started' },
  { kind: 'message', ts: 1010, stage: 'grounding', text: 'Task profile: mil_classification / slide\nextractor_name: virchow2\nRun ABMIL baseline' },
  { kind: 'heartbeat', ts: 1012, status: 'running' },
  { kind: 'tool_call', ts: 1020, ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'run_experiment', summary: 'run_experiment' },
  { kind: 'tool_observation', ts: 1035, ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.760 finished' },
  { kind: 'tool_call', ts: 1040, ui_kind: 'tool', stage: 'execution', iteration: 2, tool: 'validate_script', summary: 'validate_script' },
  { kind: 'tool_observation', ts: 1050, ui_kind: 'tool', stage: 'execution', iteration: 2, tool: 'validate_script', exit_code: 1, severity: 'error', summary: 'ImportError in train.py' },
  {
    kind: 'state',
    ts: 1060,
    status: 'running',
    state: {
      stage: 'execution',
      iteration_index: 2,
      max_iterations: 3,
      best_metric_value: 0.81,
      best_run_id: 'run_b',
      objective: { success_metric: 'auc', target_metric_value: 0.84, target_source: 'paper-x' },
      run_history: [
        { iteration: 1, metric_name: 'auc', metric_value: 0.76, committed: true, run_id: 'run_a' },
        { iteration: 2, metric_name: 'auc', metric_value: 0.81, committed: false, run_id: 'run_b' },
      ],
    },
  },
]

const session: AutoResearchSessionDetail = {
  session_id: 's1',
  title: 'Gastritis MIL benchmark',
  question: 'Train a model for gastritis classification',
  model: 'gpt-5.5',
  status: 'running',
  stage: 'execution',
  state: {
    ui_run_summary: {
      user_request: 'Train a slide-level gastritis classifier.',
      agent_actions: 'Grounded the task, selected Virchow2 features, and ran ABMIL experiments.',
      result: 'The best observed run reached AUC 0.810 before the stream continued.',
      brief: 'Running a Virchow2 ABMIL gastritis benchmark.',
      model: 'gpt-5.5',
    },
  },
  events,
}

describe('AutoResearchExecutionConsole', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US')
    vi.spyOn(Date, 'now').mockReturnValue(1060_000)
  })

  afterEach(async () => {
    vi.restoreAllMocks()
    await i18n.changeLanguage('en-US')
  })

  it('renders execution chrome from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')

    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.getByText('阶段时间线')).toBeInTheDocument()
    expect(screen.getByText('执行控制台')).toBeInTheDocument()
    expect(screen.getByText('运行摘要')).toBeInTheDocument()
    expect(screen.getByText('任务设置')).toBeInTheDocument()
    expect(screen.getByText('当前最佳')).toBeInTheDocument()
    expect(screen.getByText('迭代进度')).toBeInTheDocument()
    expect(screen.getByText('已用工具')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /显示原始事件/ })).toBeInTheDocument()
    expect(screen.queryByText('Execution console')).not.toBeInTheDocument()
    expect(screen.queryByText('Run summary')).not.toBeInTheDocument()
  })

  it('renders the execution plan as structured PathLab-style cards instead of raw JSON', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.getByText('Stage timeline')).toBeInTheDocument()
    expect(screen.getByText('Execution console')).toBeInTheDocument()
    expect(screen.queryByText('Target to beat')).not.toBeInTheDocument()
    expect(screen.getByText('Task type')).toBeInTheDocument()
    expect(screen.getAllByText('slide-level classification').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Foundation model').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Virchow2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MIL method').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ABMIL').length).toBeGreaterThan(0)
    expect(screen.getByText('Best so far')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download artifacts for best run/i })).toBeInTheDocument()
    expect(screen.getByText('Iteration ladder')).toBeInTheDocument()
    expect(screen.getAllByText('Iter 1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Iter 2').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /download artifacts for iter 1/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download artifacts for iter 2/i })).toBeInTheDocument()
    expect(screen.getAllByText('run_experiment').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ImportError in train.py').length).toBeGreaterThan(0)
    expect(screen.queryByText(/open stream/i)).not.toBeInTheDocument()

    expect(screen.queryByText(/"kind"/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Raw state/i)).not.toBeInTheDocument()
  })

  it('renders a run summary card and stage duration labels', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.getByText('Run summary')).toBeInTheDocument()
    expect(screen.getByText('User request')).toBeInTheDocument()
    expect(screen.getByText('Train a slide-level gastritis classifier.')).toBeInTheDocument()
    expect(screen.getByText('Agent work')).toBeInTheDocument()
    expect(screen.getByText('Ran 2 iterations. Models used: foundation model Virchow2, MIL method ABMIL, agent LLM gpt-5.5.')).toBeInTheDocument()
    expect(screen.getByText('Result')).toBeInTheDocument()
    expect(screen.getByText('The best observed run reached AUC 0.810 before the stream continued.')).toBeInTheDocument()
    expect(screen.getByText('7 events')).toBeInTheDocument()
    expect(screen.getByText('2 tools')).toBeInTheDocument()
    expect(screen.getByText('2 iterations')).toBeInTheDocument()
    expect(screen.getByText('AUC 0.810')).toBeInTheDocument()
    expect(screen.getAllByText('Grounding').length).toBeGreaterThan(0)
    expect(screen.getByTestId('autoresearch-stage-duration-grounding')).toHaveTextContent('20s')
    expect(screen.getAllByText('40s').length).toBeGreaterThan(0)
  })

  it('renders an external validation summary only when external results exist', () => {
    const externalSession: AutoResearchSessionDetail = {
      ...session,
      status: 'completed',
      stage: 'completed',
      state: {
        ...session.state,
        objective: { success_metric: 'auc' },
        external_test_history: [
          {
            run_id: 'external_run_001',
            status: 'completed',
            committed: true,
            model_path: '/workspace/outputs/best_model.pt',
            run_dir: '/workspace/runs/external_run_001',
            metrics: {
              auc: 0.91342,
              accuracy: 0.842,
              n_external_evaluated: 18,
            },
          },
        ],
      },
    }

    render(<AutoResearchExecutionConsole session={externalSession} events={events} streamStatus="closed" />)

    const externalCard = screen.getByTestId('autoresearch-external-summary')
    expect(externalCard).toHaveTextContent('External validation')
    expect(externalCard).toHaveTextContent('AUC 0.913')
    expect(externalCard).toHaveTextContent('18 samples')
    expect(externalCard).toHaveTextContent('completed')
    expect(externalCard).not.toHaveTextContent('external_run_001')
    expect(externalCard).not.toHaveTextContent('/workspace/outputs/best_model.pt')
    expect(externalCard).not.toHaveTextContent('Run dir')
  })

  it('renders current internal test metrics alongside external validation', () => {
    const completedSession: AutoResearchSessionDetail = {
      ...session,
      status: 'completed',
      stage: 'completed',
      state: {
        ...session.state,
        objective: { success_metric: 'auc' },
        selected_dataset: { name: 'Chronic-gastritis' },
        external_test_request: {
          contract: {
            datasets: [{ role: 'external', dataset_name: 'PWH-GC-IM' }],
          },
        },
        best_run_id: 'run_36962082',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_36962082',
            metric_name: 'auc',
            metric_value: 0.9757,
            committed: true,
            model_path: '/workspace/model_artifacts/run_36962082/best_model.pth',
            run_dir: 'output/runs/run_36962082',
            metrics: {
              best_val_auc: 0.9825,
              test: {
                loss: 0.329,
                accuracy: 0.8947,
                auc: 0.9757,
                f1: 0.8123,
              },
              data_coverage: {
                usable_counts: { train: 568, val: 111, test: 114 },
                missing_feature_counts: { train: 4, val: 3, test: 0 },
              },
            },
          },
        ],
        external_test_history: [
          {
            run_id: 'run_70546e4d',
            status: 'completed',
            committed: true,
            metrics: {
              auc: 0.7256,
              accuracy: 0.7838,
              coverage: { n_external_evaluated: 2697 },
            },
          },
        ],
      },
    }

    render(<AutoResearchExecutionConsole session={completedSession} events={events} streamStatus="closed" />)

    const internalCard = screen.getByTestId('autoresearch-internal-summary')
    expect(internalCard).toHaveTextContent('Internal test')
    expect(internalCard).toHaveTextContent('AUC 0.976')
    expect(internalCard).toHaveTextContent('114 samples')
    expect(internalCard).toHaveTextContent('completed')
    expect(internalCard).toHaveTextContent('Chronic-gastritis')
    expect(screen.getByTestId('autoresearch-internal-summary-badges')).toHaveClass('items-end')
    expect(screen.getByTestId('autoresearch-internal-summary-badges')).toHaveClass('sm:items-end')

    const externalCard = screen.getByTestId('autoresearch-external-summary')
    expect(externalCard).toHaveTextContent('External validation')
    expect(externalCard).toHaveTextContent('AUC 0.726')
    expect(externalCard).toHaveTextContent('2697 samples')
    expect(externalCard).toHaveTextContent('completed')
    expect(externalCard).toHaveTextContent('PWH-GC-IM')
    expect(screen.getByTestId('autoresearch-external-summary-badges')).toHaveClass('items-end')
    expect(screen.getByTestId('autoresearch-external-summary-badges')).toHaveClass('sm:items-end')
  })


  it('renders patch classification flat metrics as an internal test card', () => {
    const completedSession: AutoResearchSessionDetail = {
      ...session,
      status: 'completed',
      stage: 'completed',
      state: {
        ...session.state,
        objective: { success_metric: 'auc' },
        selected_dataset: { name: 'CRC-MSI patch' },
        best_run_id: 'run_patch',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_patch',
            metric_name: 'auc',
            metric_value: 0.7717,
            committed: true,
            status: 'completed',
            model_path: '/workspace/model_artifacts/run_patch/best_model.pth',
            run_dir: 'output/runs/run_patch',
            metrics: {
              auc: 0.7717,
              accuracy: 0.8068,
              f1: 0.6608,
              n_train: 15559,
              n_val: 3998,
              n_test: 32361,
              task_level: 'patch',
              mil_aggregation: false,
              test_metrics: {
                auc: 0.7717,
                accuracy: 0.8068,
                f1: 0.6608,
              },
            },
          },
        ],
      },
    }

    render(<AutoResearchExecutionConsole session={completedSession} events={events} streamStatus="closed" />)

    const internalCard = screen.getByTestId('autoresearch-internal-summary')
    expect(internalCard).toHaveTextContent('Internal test')
    expect(internalCard).toHaveTextContent('AUC 0.772')
    expect(internalCard).toHaveTextContent('32361 samples')
    expect(internalCard).toHaveTextContent('CRC-MSI patch')
    expect(internalCard).toHaveTextContent('completed')
  })

  it('renders internal test and external validation summaries when both results exist', () => {
    const completedSession: AutoResearchSessionDetail = {
      ...session,
      status: 'completed',
      stage: 'completed',
      state: {
        ...session.state,
        objective: { success_metric: 'auc' },
        best_run_id: 'run_train',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_train',
            committed: true,
            model_path: '/workspace/outputs/best_model.pt',
            run_dir: '/workspace/runs/run_train',
            metrics: {
              internal_test: {
                loss: 0.9798,
                accuracy: 0,
                auc: null,
                f1: 0,
                n: 1,
                coverage: 1,
                missing_feature_count: 0,
              },
            },
          },
        ],
        external_test_history: [
          {
            run_id: 'external_run_001',
            status: 'completed',
            committed: true,
            metrics: {
              auc: 0.91342,
              accuracy: 0.842,
              n_external_evaluated: 18,
            },
          },
        ],
      },
    }

    render(<AutoResearchExecutionConsole session={completedSession} events={events} streamStatus="closed" />)

    const internalCard = screen.getByTestId('autoresearch-internal-summary')
    expect(internalCard).toHaveTextContent('Internal test')
    expect(internalCard).toHaveTextContent('AUC --')
    expect(internalCard).toHaveTextContent('1 samples')
    expect(internalCard).toHaveTextContent('completed')
    expect(internalCard).not.toHaveTextContent('coverage 100%')
    expect(internalCard).not.toHaveTextContent('missing features 0')
    expect(internalCard).not.toHaveTextContent('run_train')
    expect(internalCard).not.toHaveTextContent('Model')
    expect(internalCard).not.toHaveTextContent('Run dir')

    const externalCard = screen.getByTestId('autoresearch-external-summary')
    expect(externalCard).toHaveTextContent('External validation')
    expect(externalCard).toHaveTextContent('AUC 0.913')
    expect(externalCard).toHaveTextContent('18 samples')
    expect(externalCard).toHaveTextContent('completed')
    expect(externalCard).not.toHaveTextContent('external_run_001')
    expect(externalCard).not.toHaveTextContent('Model')
    expect(externalCard).not.toHaveTextContent('Run dir')
  })

  it('does not render an empty external validation card for sessions without external results', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.queryByTestId('autoresearch-external-summary')).not.toBeInTheDocument()
    expect(screen.queryByText('External validation')).not.toBeInTheDocument()
  })

  it('does not duplicate terminal completed badges in the run summary header', () => {
    const completedEvents: AutoResearchEvent[] = [
      ...events,
      { kind: 'state', ts: 1070, status: 'completed', stage: 'completed', state: { stage: 'completed' } },
    ]
    const completedSession: AutoResearchSessionDetail = {
      ...session,
      status: 'completed',
      stage: 'completed',
      state: { ...session.state, stage: 'completed' },
      events: completedEvents,
    }

    render(<AutoResearchExecutionConsole session={completedSession} events={completedEvents} streamStatus="closed" />)

    const summaryCard = screen.getByTestId('autoresearch-summary-card')
    expect(within(summaryCard).getAllByText('completed')).toHaveLength(1)
  })

  it('renders grounding task evidence and discovered papers in the grounding stage card', () => {
    const groundingSession: AutoResearchSessionDetail = {
      ...session,
      state: {
        ...session.state,
        grounding: {
          selected_skill: 'mil_classification',
          route: 'skill',
          online_literature_count: 13,
          online_literature_providers: ['openalex', 'pubmed'],
          sota_lookup_status: 'cache_negative',
          task_profile: {
            task_type: 'mil_classification',
            asset_level: 'slide',
            prediction_target: 'NSCLC subtype classification',
          },
          papers: [
            {
              paper_id: 'lu2021clam',
              title: 'Data-efficient and weakly supervised computational pathology on whole-slide images',
              year: 2021,
              source: 'local',
              url: 'https://doi.org/10.1038/s41551-020-00682-w',
            },
            {
              paper_id: 'pmid-123',
              title: 'PubMed WSI MIL benchmark',
              year: 2024,
              source: 'pubmed',
            },
          ],
        },
      },
    }

    render(<AutoResearchExecutionConsole session={groundingSession} events={events} streamStatus="closed" />)

    const groundingDisclosure = screen.getByTestId('autoresearch-grounding-disclosure')
    expect(groundingDisclosure).not.toHaveAttribute('open')
    fireEvent.click(screen.getByTestId('autoresearch-grounding-summary'))
    expect(groundingDisclosure).toHaveAttribute('open')
    expect(screen.getByText('Grounding literature')).toBeInTheDocument()
    expect(screen.getByText('Task profile')).toBeInTheDocument()
    expect(screen.getByText('slide-level NSCLC subtype classification')).toBeInTheDocument()
    expect(screen.getByText('Selected skill')).toBeInTheDocument()
    expect(screen.getByText('mil_classification')).toBeInTheDocument()
    expect(screen.getByText('13 papers found')).toBeInTheDocument()
    expect(screen.getByText('openalex, pubmed')).toBeInTheDocument()
    expect(screen.getByText('Data-efficient and weakly supervised computational pathology on whole-slide images')).toBeInTheDocument()
    expect(screen.getByText('PubMed WSI MIL benchmark')).toBeInTheDocument()
    expect(screen.getByText('local · 2021')).toBeInTheDocument()
    expect(screen.getByText('pubmed · 2024')).toBeInTheDocument()
    expect(screen.getByText('no SOTA target found')).toBeInTheDocument()
  })

  it('renders acquisition readiness details behind an expandable acquisition card', () => {
    const acquisitionSession: AutoResearchSessionDetail = {
      ...session,
      state: {
        ...session.state,
        acquisition_status: 'prepared',
        acquisition_notes: 'Existing feature tensors detected; no download needed.',
        selected_dataset: {
          name: 'TCGA-LUAD + TCGA-LUSC',
          provider: 'local',
          access: 'existing',
        },
        dataset_manifest_path: '/data/autoresearch/manifests/nsclc.json',
        dataset_candidates: [{ name: 'TCGA-LUAD' }, { name: 'TCGA-LUSC' }],
        data_readiness: {
          status: 'features_ready',
          features_dir: '/data/features/virchow2/nsclc',
          splits_file: '/data/splits/nsclc.csv',
        },
        execution_plan: {
          status: 'ready',
          current_step: 0,
          steps: [
            {
              id: 'train_mil',
              skill: 'mil_classification',
              title: 'Train slide-level classifier',
            },
          ],
        },
      },
    }

    render(<AutoResearchExecutionConsole session={acquisitionSession} events={events} streamStatus="closed" />)

    const acquisitionDisclosure = screen.getByTestId('autoresearch-acquisition-disclosure')
    expect(acquisitionDisclosure).not.toHaveAttribute('open')
    expect(screen.getByText('Acquisition prepared: features_ready.')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('autoresearch-acquisition-summary'))

    expect(acquisitionDisclosure).toHaveAttribute('open')
    expect(screen.getByText('Data acquisition')).toBeInTheDocument()
    expect(screen.getByText('TCGA-LUAD + TCGA-LUSC')).toBeInTheDocument()
    expect(screen.getByText('local · existing')).toBeInTheDocument()
    expect(screen.getAllByText('features_ready').length).toBeGreaterThan(0)
    expect(screen.getByText('/data/features/virchow2/nsclc')).toBeInTheDocument()
    expect(screen.getByText('/data/splits/nsclc.csv')).toBeInTheDocument()
    expect(screen.getByText('Train slide-level classifier')).toBeInTheDocument()
  })

  it('renders live dataset download progress in the acquisition card', () => {
    const downloadingSession: AutoResearchSessionDetail = {
      ...session,
      stage: 'acquisition',
      state: {
        ...session.state,
        stage: 'acquisition',
        acquisition_status: 'downloading',
        selected_dataset: {
          name: 'PANDA',
          provider: 'kaggle',
          access: 'manual',
        },
        download_progress: {
          status: 'downloading',
          dataset_id: 'kaggle:prostate-cancer-grade-assessment',
          provider: 'kaggle',
          downloaded_bytes: 5 * 1024 * 1024,
          bytes_total: 20 * 1024 * 1024,
          speed_bps: 1024 * 1024,
          eta_seconds: 15,
          current_file: 'panda.zip',
        },
      },
    }

    render(<AutoResearchExecutionConsole session={downloadingSession} events={events} streamStatus="open" />)

    fireEvent.click(screen.getByTestId('autoresearch-acquisition-summary'))

    expect(screen.getByText('Download progress')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByText('5.0MB / 20.0MB')).toBeInTheDocument()
    expect(screen.getAllByText('1.0MB/s').length).toBeGreaterThan(0)
    expect(screen.getByText('ETA 15s')).toBeInTheDocument()
    expect(screen.getByText('panda.zip')).toBeInTheDocument()
  })

  it('shows download activity while acquisition is collapsed when total size is unknown', () => {
    const downloadingSession: AutoResearchSessionDetail = {
      ...session,
      stage: 'acquisition',
      state: {
        ...session.state,
        stage: 'acquisition',
        acquisition_status: 'downloading',
        download_progress: {
          status: 'downloading',
          dataset_id: 'kaggle:prostate-cancer-grade-assessment',
          provider: 'kaggle',
          downloaded_bytes: 156 * 1024 * 1024 * 1024,
          bytes_total: 0,
          speed_bps: 25 * 1024 * 1024,
          current_file: 'prostate-cancer-grade-assessment.zip',
        },
      },
    }

    render(<AutoResearchExecutionConsole session={downloadingSession} events={events} streamStatus="open" />)

    const miniProgress = screen.getByTestId('autoresearch-download-progress-mini')
    expect(miniProgress).toHaveTextContent('156.0GB downloaded')
    expect(miniProgress).toHaveTextContent('total size unknown')
    expect(miniProgress).toHaveTextContent('25.0MB/s')
    expect(screen.getByTestId('autoresearch-acquisition-disclosure')).not.toHaveAttribute('open')

    fireEvent.click(screen.getByTestId('autoresearch-acquisition-summary'))

    expect(screen.getByTestId('autoresearch-download-progress')).toHaveTextContent('156.0GB downloaded')
    expect(screen.getByTestId('autoresearch-download-progress')).toHaveTextContent('Total size unknown')
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('keeps the raw event stream behind an explicit debug toggle', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.queryByText(/"kind"/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /show raw events/i }))

    expect(screen.getByText(/"kind"/)).toBeInTheDocument()
    expect(screen.getByText(/"tool": "run_experiment"/)).toBeInTheDocument()
  })

  it('keeps execution iteration cards collapsed by default and expandable while running', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    const firstIteration = screen.getByTestId('autoresearch-iteration-1')
    const secondIteration = screen.getByTestId('autoresearch-iteration-2')

    expect(firstIteration).not.toHaveAttribute('open')
    expect(secondIteration).not.toHaveAttribute('open')

    fireEvent.click(screen.getByTestId('autoresearch-iteration-summary-1'))
    fireEvent.click(screen.getByTestId('autoresearch-iteration-summary-2'))

    expect(firstIteration).toHaveAttribute('open')
    expect(secondIteration).toHaveAttribute('open')
    expect(firstIteration).toHaveTextContent('run_experiment')
    expect(secondIteration).toHaveTextContent('ImportError in train.py')
  })

  it('shows live iteration progress in both the execution console and iteration ladder', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.getByTestId('autoresearch-execution-running-badge')).toHaveTextContent('Iter 2/3 running')
    expect(screen.getByTestId('autoresearch-ladder-running-strip')).toHaveTextContent('Iter 2/3 running')
    expect(screen.getByTestId('autoresearch-iteration-2')).toHaveTextContent('Running iteration')
  })

  it('shows live epoch training progress from the session summary', () => {
    const trainingSession: AutoResearchSessionDetail = {
      ...session,
      training_progress: {
        run_id: 'run_b',
        current_epoch: 7,
        total_epochs: 30,
        current_val_auc: 0.9636,
        best_val_auc: 0.9683,
      },
    }

    render(<AutoResearchExecutionConsole session={trainingSession} events={events} streamStatus="open" />)

    const progress = screen.getByTestId('autoresearch-training-progress-badge')
    expect(progress).toHaveTextContent('Epoch 7/30')
    expect(progress).toHaveTextContent('val AUC 0.964')
    expect(progress).toHaveTextContent('best 0.968')
  })

  it('hides stale epoch training progress after the session finishes', () => {
    const completedTrainingSession: AutoResearchSessionDetail = {
      ...session,
      status: 'running',
      stage: 'completed',
      training_progress: {
        run_id: 'run_b',
        current_epoch: 7,
        total_epochs: 30,
        current_val_auc: 0.9636,
        best_val_auc: 0.9683,
      },
    }

    render(<AutoResearchExecutionConsole session={completedTrainingSession} events={events} streamStatus="closed" />)

    expect(screen.queryByTestId('autoresearch-training-progress-badge')).not.toBeInTheDocument()
  })

  it('maps zero-based live iteration state to the displayed running iteration', () => {
    const zeroBasedEvents: AutoResearchEvent[] = [
      { kind: 'tool_call', ts: 1020, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'baseline run' },
      { kind: 'tool_observation', ts: 1035, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.760 finished' },
      {
        kind: 'state',
        ts: 1040,
        status: 'running',
        state: {
          stage: 'execution',
          iteration_index: 1,
          max_iterations: 5,
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.76, committed: true, run_id: 'run_a' },
          ],
        },
      },
      { kind: 'tool_call', ts: 1050, ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'run_experiment', summary: 'second run' },
    ]
    const zeroBasedSession: AutoResearchSessionDetail = {
      ...session,
      state: { stage: 'execution', iteration_index: 1, max_iterations: 5 },
      events: zeroBasedEvents,
    }

    render(<AutoResearchExecutionConsole session={zeroBasedSession} events={zeroBasedEvents} streamStatus="open" />)

    expect(screen.getByTestId('autoresearch-execution-running-badge')).toHaveTextContent('Iter 2/5 running')
    expect(within(screen.getByTestId('autoresearch-iteration-1')).queryByText('Running')).not.toBeInTheDocument()
    expect(within(screen.getByTestId('autoresearch-iteration-2')).getByText('Running')).toBeInTheDocument()
  })

  it('labels each slide-level iteration with foundation model and MIL method', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    const firstIteration = screen.getByTestId('autoresearch-iteration-1')

    expect(firstIteration).toHaveTextContent('Foundation model')
    expect(firstIteration).toHaveTextContent('Virchow2')
    expect(firstIteration).toHaveTextContent('MIL method')
    expect(firstIteration).toHaveTextContent('ABMIL')
  })

  it('does not show a MIL method badge for patch-level iteration cards', () => {
    const patchEvents: AutoResearchEvent[] = [
      { kind: 'message', ts: 1010, stage: 'grounding', text: 'Task profile: patch_classification / patch\nextractor_name: virchow2' },
      { kind: 'tool_call', ts: 1020, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'patch classifier' },
      { kind: 'tool_observation', ts: 1035, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.760 finished' },
    ]
    const patchSession: AutoResearchSessionDetail = {
      ...session,
      question: 'Use Virchow2 to train a patch-level classification model.',
      state: { objective: { question: 'patch-level classification' } },
      events: patchEvents,
    }

    render(<AutoResearchExecutionConsole session={patchSession} events={patchEvents} streamStatus="closed" />)

    const firstIteration = screen.getByTestId('autoresearch-iteration-1')
    expect(firstIteration).toHaveTextContent('Foundation model')
    expect(firstIteration).toHaveTextContent('Virchow2')
    expect(firstIteration).not.toHaveTextContent('MIL method')
  })

  it('does not show a stale static status pill on the current running iteration card', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    const runningCard = screen.getByTestId('autoresearch-iteration-2')

    expect(within(runningCard).getByText('Running')).toBeInTheDocument()
    expect(within(runningCard).queryByText('not committed')).not.toBeInTheDocument()
  })

  it('shows a running placeholder when execution has started before the first tool event', () => {
    const bootingSession: AutoResearchSessionDetail = {
      ...session,
      state: { stage: 'execution', iteration_index: 0, max_iterations: 5 },
      events: [
        { kind: 'session', ts: 1000, status: 'running', stage: 'execution', summary: 'Session started' },
        { kind: 'state', ts: 1001, status: 'running', state: { stage: 'execution', iteration_index: 0, max_iterations: 5 } },
      ],
    }

    render(<AutoResearchExecutionConsole session={bootingSession} events={bootingSession.events} streamStatus="open" />)

    expect(screen.getByTestId('autoresearch-execution-running-badge')).toHaveTextContent('Iter 1/5 running')
    expect(screen.getByTestId('autoresearch-ladder-running-strip')).toHaveTextContent('Iter 1/5 running')
    expect(screen.getByTestId('autoresearch-iteration-running-placeholder')).toHaveTextContent('Iter 1')
    expect(screen.getByTestId('autoresearch-ladder-running-placeholder')).toHaveTextContent('Iter 1')
  })

  it('does not render the developer stream status footer in the main run UI', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.queryByTestId('autoresearch-status-bar')).not.toBeInTheDocument()
    expect(screen.queryByText(/open stream/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/normalized events/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /pause/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeInTheDocument()
  })

  it('stretches the execution console so its bottom aligns with the right tools column', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    expect(screen.getByTestId('autoresearch-console-layout')).toHaveClass('items-stretch')
    expect(screen.getByTestId('autoresearch-console-layout')).toHaveClass('xl:h-[calc(100vh-18rem)]')
    expect(screen.getByTestId('autoresearch-console-layout')).toHaveClass('xl:min-h-[920px]')
    expect(screen.getByTestId('autoresearch-main-column')).toHaveClass('h-full')
    expect(screen.getByTestId('autoresearch-main-column')).toHaveClass('min-h-0')
    expect(screen.getByTestId('autoresearch-main-column')).toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('autoresearch-events-card')).toHaveClass('flex-1')
    expect(screen.getByTestId('autoresearch-events-card')).toHaveClass('xl:min-h-0')
    expect(screen.getByTestId('autoresearch-events-card')).toHaveClass('overflow-hidden')
    expect(screen.getByTestId('autoresearch-events-scroll')).toHaveClass('overflow-y-auto')
    expect(screen.getByTestId('autoresearch-events-scroll')).toHaveClass('min-h-0')
    expect(screen.getByTestId('autoresearch-events-scroll')).not.toHaveClass('min-h-[720px]')
  })

  it('shows all pipeline stages with durations in clinical execution console cards', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" variant="clinical" />)

    expect(screen.queryByText('Stage timeline')).not.toBeInTheDocument()
    expect(screen.queryByText('Compressed transcript')).not.toBeInTheDocument()
    expect(screen.queryByText('Gastritis MIL benchmark')).not.toBeInTheDocument()
    expect(screen.queryByText('LLM summary')).not.toBeInTheDocument()
    expect(screen.queryByTestId('autoresearch-stage-timeline-embedded')).not.toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-stage-card-intake')).toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-stage-card-grounding')).toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-stage-card-acquisition')).toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-stage-card-pre_execution_ready')).toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-stage-duration-grounding')).toHaveTextContent('20s')
  })

  it('limits the clinical execution console to three visible steps with a styled scrollbar', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" variant="clinical" />)

    const layout = screen.getByTestId('autoresearch-console-layout')
    const eventsCard = screen.getByTestId('autoresearch-events-card')
    const eventsScroll = screen.getByTestId('autoresearch-events-scroll')
    const sidebar = screen.getByTestId('autoresearch-sidebar')
    const ladderCard = screen.getByTestId('autoresearch-iteration-ladder-card')

    expect(layout).toHaveClass('items-start')
    expect(layout).not.toHaveClass('h-[min(720px,70vh)]')
    expect(eventsCard).toHaveClass('flex-shrink-0')
    expect(eventsScroll).toHaveClass('autoresearch-steps-scroll')
    expect(eventsScroll).toHaveClass('custom-scrollbar')
    expect(eventsScroll).toHaveClass('overflow-y-auto')
    expect(sidebar).toHaveClass('xl:self-start')
    expect(ladderCard).toHaveClass('min-h-[280px]')
    expect(ladderCard).toHaveClass('max-h-[360px]')
    expect(screen.getByTestId('autoresearch-iteration-ladder-scroll')).toHaveClass('custom-scrollbar')
    expect(screen.getByText('Iteration ladder')).toBeVisible()
  })

  it('places run summary in the same left column as the execution console and lifts task setup to the right column top', () => {
    render(<AutoResearchExecutionConsole session={session} events={events} streamStatus="open" />)

    const mainColumn = screen.getByTestId('autoresearch-main-column')
    const summaryCard = screen.getByTestId('autoresearch-summary-card')
    const eventsCard = screen.getByTestId('autoresearch-events-card')
    const sidebar = screen.getByTestId('autoresearch-sidebar')

    expect(mainColumn).toContainElement(summaryCard)
    expect(mainColumn).toContainElement(eventsCard)
    expect(sidebar).toHaveTextContent('Task setup')
    expect(sidebar).toHaveClass('xl:flex')
    expect(sidebar).not.toHaveClass('xl:h-full')
    expect(sidebar).not.toHaveClass('xl:overflow-hidden')
    expect(sidebar).not.toHaveClass('xl:overflow-y-auto')
    expect(sidebar).toHaveClass('xl:self-start')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).not.toHaveClass('xl:flex-1')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).toHaveClass('xl:min-h-[320px]')
    expect(screen.getByTestId('autoresearch-iteration-ladder-card')).not.toHaveClass('xl:overflow-hidden')
    expect(screen.getByTestId('autoresearch-iteration-ladder-scroll')).toHaveClass('overflow-y-auto')
    expect(screen.getByTestId('autoresearch-tools-card')).not.toHaveClass('xl:mt-auto')
  })
})
