import { describe, expect, it } from 'vitest'
import { buildPathScientistExecutionView } from '@renderer/lib/pathscientistEventSelectors'
import type { PathScientistEvent, PathScientistSessionDetail } from '@renderer/types/pathscientist'

describe('pathscientist event selectors', () => {
  it('builds a stage timeline, iteration ladder, tool cards, and current activity', () => {
    const events: PathScientistEvent[] = [
      { kind: 'session', status: 'running', stage: 'grounding', summary: 'Session started' },
      { kind: 'heartbeat', status: 'running' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'run_experiment' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'run_experiment finished' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'validate_script', summary: 'validate_script' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'validate_script', exit_code: 1, summary: 'validate_script failed', severity: 'error' },
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          iteration_index: 2,
          max_iterations: 3,
          best_metric_value: 0.81,
          best_run_id: 'run_b',
          objective: { success_metric: 'auc', target_metric_value: 0.84, target_source: 'paper-x' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.76, committed: true, run_id: 'run_a' },
            { iteration: 1, metric_name: 'auc', metric_value: 0.81, committed: true, run_id: 'run_b' },
          ],
        },
      },
    ]
    const session = {
      session_id: 's1',
      title: 'Gastritis MIL',
      question: 'Train a model',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.visibleEvents.map((event) => event.kind)).not.toContain('heartbeat')
    expect(view.stages.find((stage) => stage.id === 'execution')?.status).toBe('complete')
    expect(view.stages.find((stage) => stage.id === 'completed')?.status).toBe('complete')
    expect(view.iterations).toHaveLength(2)
    expect(view.iterations[1].metricValue).toBe(0.81)
    expect(view.iterations[1].tools[0].status).toBe('error')
    expect(view.toolCards.map((tool) => tool.tool)).toEqual(['run_experiment', 'validate_script'])
    expect(view.bestMetric).toEqual({ name: 'auc', value: 0.81, runId: 'run_b' })
    expect(view.targetMetric).toEqual({ name: 'auc', value: 0.84, source: 'paper-x' })
    expect(view.currentActivity?.label).toBe('Session completed')
  })

  it('reads iteration AUC from nested run metrics when metric_value is missing', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          max_iterations: 5,
          best_metric_value: 0.9632,
          best_run_id: null,
          objective: { success_metric: 'auc' },
          run_history: [
            {
              iteration: 0,
              metric_name: 'auc',
              metric_value: null,
              committed: true,
              run_id: 'run_a',
              metrics: { best_val_auc: 0.9921, test: { auc: 0.9629, accuracy: 0.878 } },
            },
            {
              iteration: 4,
              metric_name: 'auc',
              metric_value: null,
              committed: true,
              run_id: 'run_b',
              metrics: { best_val_auc: 0.9921, test: { auc: 0.9632, accuracy: 0.879 } },
            },
          ],
        },
      },
    ]
    const session = {
      session_id: 's-nested-metrics',
      title: 'Nested metrics run',
      question: 'Train a WSI classifier',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.iterations.map((iteration) => iteration.metricValue)).toEqual([0.9629, 0.9632])
    expect(view.bestMetric).toEqual({ name: 'auc', value: 0.9632, runId: 'run_b' })
  })

  it('treats completed workflow with no committed run and failed review as failed', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          review_decision: 'enter_synthesis',
          latest_review: {
            status: 'failed',
            decision: 'enter_synthesis',
            summary: 'Run run_bad did not provide a valid positive AUC metric.',
          },
          objective: { success_metric: 'auc' },
          run_history: [
            {
              iteration: 0,
              run_id: 'run_bad',
              metric_name: 'auc',
              metric_value: 0,
              committed: false,
              exit_code: 1,
              error_type: 'FileNotFound',
              metrics: {
                status: 'failed',
                error: 'Required FEATURES_DIR does not exist.',
              },
            },
          ],
        },
      },
    ]
    const session = {
      session_id: 's-failed-science',
      title: 'Failed external feature run',
      question: 'Train then external validate',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.runSummary.status).toBe('failed')
    expect(view.stages.find((stage) => stage.id === 'completed')?.status).toBe('error')
    expect(view.bestMetric).toBeNull()
  })

  it('infers task type, foundation model, and MIL method for slide-level sessions', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'message',
        stage: 'grounding',
        text: [
          'Task profile: mil_classification / slide',
          'Prepared contract:',
          '- task_type: mil_classification',
          '- extractor_name: virchow2',
          'Run full ABMIL training baseline',
        ].join('\n'),
      },
      {
        kind: 'tool_call',
        stage: 'execution',
        iteration: 1,
        tool: 'run_experiment',
        summary: 'mil_classification ABMIL baseline',
      },
    ]
    const session = {
      session_id: 's2',
      title: 'Chronic gastritis MIL',
      question: 'Use virchow2 features to train a WSI MIL classifier.',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { question: 'slide-level inflammation grading classification' },
      },
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.sessionMetadata).toEqual({
      taskType: 'slide-level classification',
      foundationModel: 'Virchow2',
      milMethod: 'ABMIL',
    })
  })

  it('uses the explicit grounded MIL selection instead of literature keyword matches', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'running',
        state: {
          stage: 'execution',
          grounding: {
            task_profile: { task_type: 'mil_classification', asset_level: 'slide' },
            selected_extractor: { name: 'virchow2', canonical: 'Virchow2', source: 'user' },
            selected_mil_model: { name: 'abmil', canonical: 'ABMIL', source: 'user' },
            model_selection_contract: {
              mil_model: { name: 'abmil', canonical: 'ABMIL', source: 'user' },
            },
            papers: [
              {
                paper_id: 'zhang2022dtfd',
                title: 'DTFD-MIL: Double-Tier Feature Distillation Multiple Instance Learning',
              },
              {
                paper_id: 'shao2021transmil',
                title: 'TransMIL: Transformer based Correlated Multiple Instance Learning',
              },
            ],
          },
        },
      },
      {
        kind: 'message',
        stage: 'execution',
        text: 'Available methods include DTFD-MIL and TransMIL, but the requested run uses ABMIL.',
      },
    ]
    const session = {
      session_id: 's-selected-mil',
      title: 'NSCLC ABMIL Classification with Virchow2',
      question: '帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature',
      model: 'gpt-5.5',
      status: 'running',
      stage: 'execution',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.sessionMetadata).toMatchObject({
      taskType: 'slide-level classification',
      foundationModel: 'Virchow2',
      milMethod: 'ABMIL',
    })
  })


  it('uses explicit task profile before literature survival keywords', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'running',
        state: {
          stage: 'execution',
          task_profile: { task_type: 'mil_classification', asset_level: 'slide' },
          grounding: {
            task_profile: { task_type: 'mil_classification', asset_level: 'slide' },
            selected_extractor: { canonical: 'Virchow2' },
            selected_mil_model: { canonical: 'CLAM-MB' },
            papers: [
              {
                paper_id: 'survival-paper',
                title: 'Slide-level survival prediction with weakly supervised pathology models',
              },
            ],
          },
        },
      },
      {
        kind: 'message',
        stage: 'grounding',
        text: 'The literature corpus includes survival prediction papers, but the current run is NSCLC slide MIL classification.',
      },
    ]
    const session = {
      session_id: 's-task-profile-priority',
      title: 'NSCLC classification run',
      question: 'Use Virchow2 and CLAM for NSCLC LUAD vs LUSC classification.',
      model: 'gpt-5.5',
      status: 'running',
      stage: 'execution',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.sessionMetadata).toMatchObject({
      taskType: 'slide-level classification',
      foundationModel: 'Virchow2',
      milMethod: 'CLAM',
    })
  })

  it('normalizes grounding task profile and literature papers for the grounding card', () => {
    const session = {
      session_id: 's-grounding',
      title: 'Grounding literature run',
      question: 'Find papers for NSCLC MIL classification.',
      status: 'completed',
      stage: 'completed',
      state: {
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
              year: '2024',
              source: 'pubmed',
            },
          ],
        },
      },
      events: [
        {
          kind: 'state',
          status: 'completed',
          state: {
            stage: 'completed',
            run_history: [
              {
                iteration: 0,
                run_id: 'run_train',
                committed: true,
                metric_name: 'external_auc',
                metric_value: 0.5556,
              },
            ],
          },
        },
      ],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, session.events)

    expect((view as any).grounding).toMatchObject({
      selectedSkill: 'mil_classification',
      route: 'skill',
      literatureCount: 13,
      providers: ['openalex', 'pubmed'],
      sotaStatusLabel: 'no SOTA target found',
      taskProfile: {
        taskType: 'mil_classification',
        assetLevel: 'slide',
        predictionTarget: 'NSCLC subtype classification',
      },
      papers: [
        {
          id: 'lu2021clam',
          title: 'Data-efficient and weakly supervised computational pathology on whole-slide images',
          year: '2021',
          source: 'local',
          url: 'https://doi.org/10.1038/s41551-020-00682-w',
        },
        {
          id: 'pmid-123',
          title: 'PubMed WSI MIL benchmark',
          year: '2024',
          source: 'pubmed',
        },
      ],
    })
  })

  it('normalizes acquisition data readiness and execution plan for the acquisition card', () => {
    const session = {
      session_id: 's-acquisition',
      title: 'Acquisition run',
      question: 'Prepare TCGA LUAD/LUSC Virchow2 features.',
      status: 'completed',
      stage: 'completed',
      state: {
        acquisition_status: 'prepared',
        acquisition_notes: 'Existing feature tensors detected; no download needed.',
        selected_dataset: {
          name: 'TCGA-LUAD + TCGA-LUSC',
          provider: 'local',
          access: 'existing',
        },
        dataset_manifest_path: '/data/pathscientist/manifests/nsclc.json',
        dataset_candidates: [{ name: 'TCGA-LUAD' }, { name: 'TCGA-LUSC' }],
        data_readiness: {
          status: 'features_ready',
          features_dir: '/data/features/virchow2/nsclc',
          splits_file: '/data/splits/nsclc.csv',
          missing: [],
        },
        execution_plan: {
          status: 'ready',
          current_step: 0,
          steps: [
            {
              id: 'train_mil',
              skill: 'mil_classification',
              title: 'Train slide-level classifier',
              inputs: {
                features_dir: '/data/features/virchow2/nsclc',
                splits_file: '/data/splits/nsclc.csv',
              },
            },
          ],
          notes: ['Existing feature tensors + splits detected; train directly.'],
        },
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect((view as any).acquisition).toMatchObject({
      status: 'prepared',
      notes: 'Existing feature tensors detected; no download needed.',
      selectedDataset: {
        name: 'TCGA-LUAD + TCGA-LUSC',
        provider: 'local',
        access: 'existing',
      },
      datasetCandidateCount: 2,
      manifestPath: '/data/pathscientist/manifests/nsclc.json',
      readinessStatus: 'features_ready',
      missing: [],
      planStatus: 'ready',
      paths: [
        { label: 'features_dir', value: '/data/features/virchow2/nsclc' },
        { label: 'splits_file', value: '/data/splits/nsclc.csv' },
      ],
      planSteps: [
        {
          id: 'train_mil',
          skill: 'mil_classification',
          title: 'Train slide-level classifier',
          isCurrent: true,
        },
      ],
    })
    expect(view.stages.find((stage) => stage.id === 'acquisition')?.summary).toBe(
      'Acquisition prepared: features_ready.',
    )
  })

  it('normalizes download progress for the acquisition card', () => {
    const session = {
      session_id: 's-download-progress',
      title: 'Download run',
      question: 'Download PANDA.',
      status: 'running',
      stage: 'acquisition',
      state: {
        stage: 'acquisition',
        acquisition_status: 'downloading',
        download_progress: {
          status: 'downloading',
          dataset_id: 'kaggle:panda',
          provider: 'kaggle',
          downloaded_bytes: 5 * 1024 * 1024,
          bytes_total: 20 * 1024 * 1024,
          speed_bps: 1024 * 1024,
          eta_seconds: 15,
          current_file: 'panda.zip',
        },
      },
      events: [
        {
          kind: 'state',
          status: 'running',
          state: { stage: 'acquisition' },
        },
      ],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, session.events)

    expect((view.acquisition as any).downloadProgress).toMatchObject({
      status: 'downloading',
      datasetId: 'kaggle:panda',
      provider: 'kaggle',
      downloadedBytes: 5 * 1024 * 1024,
      bytesTotal: 20 * 1024 * 1024,
      speedBps: 1024 * 1024,
      etaSeconds: 15,
      currentFile: 'panda.zip',
      percent: 25,
    })
  })

  it('shows backend zero-based iterations as one-based and folds post-budget cleanup into the final iteration', () => {
    const events: PathScientistEvent[] = [
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'first run' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'first run finished' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 5, tool: 'file_editor', summary: 'post-budget cleanup' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 5, tool: 'file_editor', exit_code: 0, summary: 'cleanup finished' },
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          iteration_index: 5,
          max_iterations: 5,
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.71, committed: true, run_id: 'run_0' },
            { iteration: 1, metric_name: 'auc', metric_value: 0.72, committed: true, run_id: 'run_1' },
            { iteration: 2, metric_name: 'auc', metric_value: 0.73, committed: true, run_id: 'run_2' },
            { iteration: 3, metric_name: 'auc', metric_value: 0.74, committed: true, run_id: 'run_3' },
            { iteration: 4, metric_name: 'auc', metric_value: 0.75, committed: true, run_id: 'run_4' },
          ],
        },
      },
    ]
    const session = {
      session_id: 's3',
      title: 'Budgeted MIL run',
      question: 'Train for five iterations',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.iterations.map((iteration) => iteration.index)).toEqual([1, 2, 3, 4, 5])
    expect(view.toolCards.map((tool) => tool.iteration)).toEqual([1, 5])
    expect(view.iterations.at(-1)?.tools.map((tool) => tool.summary)).toContain('cleanup finished')
  })

  it('uses the run history outcome for an iteration even when a quick precheck tool failed first', () => {
    const events: PathScientistEvent[] = [
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'quick check' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 1, severity: 'error', summary: 'quick check failed' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'full run' },
      { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'full run finished' },
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          max_iterations: 3,
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.81, committed: true, run_id: 'run_a' },
          ],
        },
      },
    ]

    const view = buildPathScientistExecutionView(null, events)

    expect(view.iterations).toHaveLength(1)
    expect(view.iterations[0]).toMatchObject({
      index: 1,
      status: 'success',
      committed: true,
      metricValue: 0.81,
      runId: 'run_a',
    })
  })

  it('derives a run summary and stage durations from timestamped events', () => {
    const events: PathScientistEvent[] = [
      { kind: 'session', ts: 1000, status: 'running', stage: 'grounding', summary: 'Session started' },
      { kind: 'message', ts: 1010, stage: 'grounding', text: 'Task profile: mil_classification / slide\nextractor_name: virchow2' },
      { kind: 'message', ts: 1040, stage: 'acquisition', summary: 'Dataset located' },
      { kind: 'tool_call', ts: 1060, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'run baseline' },
      { kind: 'tool_observation', ts: 1090, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.82' },
      {
        kind: 'state',
        ts: 1120,
        status: 'completed',
        state: {
          stage: 'completed',
          iteration_index: 1,
          max_iterations: 3,
          best_metric_value: 0.82,
          best_run_id: 'run_a',
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.82, committed: true, run_id: 'run_a' },
          ],
        },
      },
    ]
    const session = {
      session_id: 's4',
      title: 'Timestamped MIL run',
      question: 'Train a timestamped run',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.runSummary).toMatchObject({
      title: 'Timestamped MIL run',
      status: 'completed',
      stage: 'completed',
      totalDurationLabel: '2m 0s',
      eventCount: 6,
      toolCallCount: 1,
      iterationCount: 1,
      currentActivityLabel: 'Session completed',
    })
    expect(view.runSummary.bestMetric).toEqual({ name: 'auc', value: 0.82, runId: 'run_a' })
    expect(view.stages.find((stage) => stage.id === 'grounding')?.durationLabel).toBe('40s')
    expect(view.stages.find((stage) => stage.id === 'acquisition')?.durationLabel).toBe('20s')
    expect(view.stages.find((stage) => stage.id === 'execution')?.durationLabel).toBe('1m 0s')
    expect(view.stages.find((stage) => stage.id === 'review')?.durationLabel).toBe('--')
  })

  it('keeps elapsed time moving for the current running stage', () => {
    const events: PathScientistEvent[] = [
      { kind: 'session', ts: 1000, status: 'running', stage: 'intake', summary: 'Session started' },
      { kind: 'message', ts: 1030, stage: 'grounding', summary: 'Grounding task' },
      { kind: 'tool_call', ts: 1060, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'run baseline' },
    ]
    const session = {
      session_id: 's-running',
      title: 'Running run',
      question: 'Run a live session',
      status: 'running',
      stage: 'execution',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events, 1125_000)

    expect(view.stages.find((stage) => stage.id === 'execution')?.status).toBe('current')
    expect(view.stages.find((stage) => stage.id === 'execution')?.durationLabel).toBe('1m 5s')
    expect(view.runSummary.totalDurationLabel).toBe('2m 5s')
  })

  it('uses the persisted LLM run summary instead of the latest agent message', () => {
    const longFinalMessage = [
      '当前无法继续新的改进实验：虽然提示里显示 Previous iterations: 4，',
      '但平台实际 metrics history 已记录 5 条 iteration，并且再次启动 run_experiment 已被拒绝。',
    ].join('')
    const events: PathScientistEvent[] = [
      { kind: 'session', ts: 1000, status: 'running', stage: 'grounding', summary: 'Session started' },
      { kind: 'message', ts: 1010, stage: 'execution', text: longFinalMessage },
      {
        kind: 'state',
        ts: 1020,
        status: 'completed',
        state: {
          stage: 'completed',
          best_metric_value: 0.9806,
          best_run_id: 'run_best',
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.95, committed: true, run_id: 'run_a' },
            { iteration: 1, metric_name: 'auc', metric_value: 0.9806, committed: true, run_id: 'run_best' },
          ],
          ui_run_summary: {
            user_request: 'Build a slide-level chronic gastritis classifier with Virchow2 features.',
            agent_actions: 'Prepared the dataset, ran MIL training experiments, tracked metrics, and reviewed the best run.',
            result: 'The best completed run reached AUC 0.9806 and was selected as the final result.',
            brief: 'Completed a Virchow2 MIL benchmark for chronic gastritis classification.',
            model: 'gpt-5.5',
          },
        },
      },
    ]
    const session = {
      session_id: 's-summary',
      title: 'Chronic gastritis MIL',
      question: 'Use Virchow2 features to train a chronic gastritis WSI ABMIL classifier.',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect((view.runSummary as any).narrative).toEqual({
      userRequest: 'Build a slide-level chronic gastritis classifier with Virchow2 features.',
      agentActions: 'Ran 2 iterations. Models used: foundation model Virchow2, MIL method ABMIL, agent LLM gpt-5.5.',
      result: 'The best completed run reached AUC 0.9806 and was selected as the final result.',
      brief: 'Completed a Virchow2 MIL benchmark for chronic gastritis classification.',
      source: 'llm',
      model: 'gpt-5.5',
    })
    expect(JSON.stringify((view.runSummary as any).narrative)).not.toContain('当前无法继续新的改进实验')
  })

  it('uses iteration numbers instead of run IDs in fallback result summaries', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'completed',
        state: {
          stage: 'completed',
          best_metric_value: 0.9642,
          best_run_id: 'run_0f5d3181',
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.951, committed: true, run_id: 'run_first' },
            { iteration: 1, metric_name: 'auc', metric_value: 0.9642, committed: true, run_id: 'run_0f5d3181' },
          ],
        },
      },
    ]
    const session = {
      session_id: 's-result-iteration',
      title: 'NSCLC MIL',
      question: 'Train an NSCLC slide-level ABMIL classifier.',
      model: 'gpt-5.5',
      status: 'completed',
      stage: 'completed',
      events,
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, events)

    expect(view.runSummary.narrative.result).toBe('The best detected result is AUC 0.964 from iteration 2.')
    expect(view.runSummary.narrative.result).not.toContain('run_0f5d3181')
  })

  it('repairs live streams that duplicated observations as iter-zero tool calls', () => {
    const events: PathScientistEvent[] = [
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'validate_script', action: { kind: 'ValidateScriptAction' }, summary: 'validate first' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'validate_script', action: null, summary: 'validate first finished' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', action: { kind: 'RunExperimentAction' }, summary: 'run first' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', action: null, summary: 'run first finished' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'ratchet_revert', action: { kind: 'RatchetRevertAction' }, summary: 'revert first' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'ratchet_revert', action: null, summary: 'revert first finished' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'validate_script', action: { kind: 'ValidateScriptAction' }, summary: 'validate second' },
      { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'validate_script', action: null, summary: 'validate second finished' },
      {
        kind: 'state',
        status: 'running',
        state: {
          stage: 'execution',
          max_iterations: 5,
          objective: { success_metric: 'auc' },
          run_history: [
            { iteration: 0, metric_name: 'auc', metric_value: 0.91, committed: false, run_id: 'run_first' },
            { iteration: 1, metric_name: 'auc', metric_value: 0.92, committed: false, run_id: 'run_second' },
          ],
        },
      },
    ]

    const view = buildPathScientistExecutionView(null, events)

    expect(view.iterations.map((iteration) => iteration.index)).toEqual([1, 2])
    expect(view.iterations[0].tools.map((tool) => tool.summary)).toEqual([
      'validate first finished',
      'run first finished',
      'revert first finished',
    ])
    expect(view.iterations[1].tools.map((tool) => tool.summary)).toEqual(['validate second finished'])
    expect(view.iterations[1].tools[0].status).toBe('success')
  })

  it('does not treat persisted synthetic stage breadcrumbs as real duration boundaries', () => {
    const events: PathScientistEvent[] = [
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1000, stage: 'intake', summary: 'Synthetic intake' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1470, stage: 'grounding', summary: 'Synthetic grounding' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1940, stage: 'acquisition', summary: 'Synthetic acquisition' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 2410, stage: 'pre_execution_ready', summary: 'Synthetic ready' },
      { kind: 'tool_call', ts: 1010, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', summary: 'run baseline' },
      { kind: 'tool_observation', ts: 1070, ui_kind: 'tool', stage: 'execution', iteration: 0, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.82' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 2880, stage: 'review', summary: 'Synthetic review' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 3350, stage: 'synthesis', summary: 'Synthetic synthesis' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 3820, stage: 'completed', summary: 'Synthetic completed' },
    ]

    const view = buildPathScientistExecutionView(null, events)

    expect(view.stages.find((stage) => stage.id === 'intake')?.durationLabel).toBe('--')
    expect(view.stages.find((stage) => stage.id === 'grounding')?.durationLabel).toBe('--')
    expect(view.stages.find((stage) => stage.id === 'acquisition')?.durationLabel).toBe('--')
    expect(view.stages.find((stage) => stage.id === 'execution')?.durationLabel).toBe('1m 0s')
    expect(view.runSummary.totalDurationLabel).toBe('47m 0s')
  })

  it('uses persisted state stage history ahead of synthetic breadcrumbs for true timings', () => {
    const events: PathScientistEvent[] = [
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1000, stage: 'intake', summary: 'Synthetic intake' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1470, stage: 'grounding', summary: 'Synthetic grounding' },
      { kind: 'stage_summary', source: 'persisted_summary', ts: 1940, stage: 'execution', summary: 'Synthetic execution' },
      {
        kind: 'state',
        ts: 3820,
        status: 'completed',
        state: {
          stage: 'completed',
          stage_history: [
            { stage: 'intake', started_at: 100, ended_at: 105, duration_sec: 5 },
            { stage: 'grounding', started_at: 105, ended_at: 117, duration_sec: 12 },
            { stage: 'execution', started_at: 117, ended_at: 157, duration_sec: 40 },
            { stage: 'completed', started_at: 157 },
          ],
        },
      },
    ]

    const view = buildPathScientistExecutionView(null, events)

    expect(view.stages.find((stage) => stage.id === 'intake')?.durationLabel).toBe('5s')
    expect(view.stages.find((stage) => stage.id === 'grounding')?.durationLabel).toBe('12s')
    expect(view.stages.find((stage) => stage.id === 'execution')?.durationLabel).toBe('40s')
    expect(view.runSummary.totalDurationLabel).toBe('57s')
  })

  it('marks the last progressed stage as error when a session is interrupted', () => {
    const session = {
      session_id: 's-interrupted-execution',
      title: 'Interrupted MIL run',
      question: 'Train a model and validate externally.',
      status: 'interrupted',
      stage: 'interrupted',
      state: {
        stage: 'interrupted',
        stage_history: [
          { stage: 'intake', started_at: 100, ended_at: 101, duration_sec: 1 },
          { stage: 'grounding', started_at: 101, ended_at: 111, duration_sec: 10 },
          { stage: 'acquisition', started_at: 111, ended_at: 123, duration_sec: 12 },
          { stage: 'pre_execution_ready', started_at: 123, ended_at: 137, duration_sec: 14 },
          { stage: 'execution', started_at: 137, ended_at: 150, duration_sec: 13 },
        ],
      },
      events: [
        { kind: 'session', ts: 100, status: 'running', stage: 'intake', summary: 'Session started' },
        { kind: 'state', ts: 150, status: 'interrupted', state: { stage: 'interrupted' } },
      ],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, session.events)

    expect(view.stages.find((stage) => stage.id === 'intake')?.status).toBe('complete')
    expect(view.stages.find((stage) => stage.id === 'pre_execution_ready')?.status).toBe('complete')
    expect(view.stages.find((stage) => stage.id === 'execution')?.status).toBe('error')
    expect(view.stages.find((stage) => stage.id === 'review')?.status).toBe('pending')
  })

  it('marks the last progressed stage as error when a session fails', () => {
    const session = {
      session_id: 's-failed-acquisition',
      title: 'Failed acquisition run',
      question: 'Download data and train a model.',
      status: 'failed',
      stage: 'failed',
      state: {
        stage: 'failed',
        stage_history: [
          { stage: 'intake', started_at: 100, ended_at: 103, duration_sec: 3 },
          { stage: 'grounding', started_at: 103, ended_at: 115, duration_sec: 12 },
          { stage: 'acquisition', started_at: 115, ended_at: 124, duration_sec: 9 },
        ],
      },
      events: [
        { kind: 'session', ts: 100, status: 'running', stage: 'intake', summary: 'Session started' },
        { kind: 'state', ts: 124, status: 'failed', state: { stage: 'failed' } },
      ],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, session.events)

    expect(view.stages.find((stage) => stage.id === 'intake')?.status).toBe('complete')
    expect(view.stages.find((stage) => stage.id === 'grounding')?.status).toBe('complete')
    expect(view.stages.find((stage) => stage.id === 'acquisition')?.status).toBe('error')
    expect(view.stages.find((stage) => stage.id === 'execution')?.status).toBe('pending')
  })

  it('summarizes stage-history-only checkpoints instead of showing zero-event fallbacks', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        status: 'running',
        state: {
          stage: 'execution',
          stage_started_at: 117,
          stage_history: [
            { stage: 'intake', started_at: 100, ended_at: 101, duration_sec: 1 },
            { stage: 'grounding', started_at: 101, ended_at: 111, duration_sec: 10 },
            { stage: 'acquisition', started_at: 111, ended_at: 116, duration_sec: 5 },
            { stage: 'pre_execution_ready', started_at: 116, ended_at: 117, duration_sec: 1 },
          ],
        },
      },
    ]

    const view = buildPathScientistExecutionView(null, events, 120_000)

    expect(view.stages.find((stage) => stage.id === 'intake')?.summary).toBe('Intake completed in 1s.')
    expect(view.stages.find((stage) => stage.id === 'grounding')?.summary).toBe('Grounding completed in 10s.')
    expect(view.stages.find((stage) => stage.id === 'acquisition')?.summary).toBe('Acquisition completed in 5s.')
    expect(view.stages.find((stage) => stage.id === 'pre_execution_ready')?.summary).toBe('Pre-exec completed in 1s.')
  })

  it('uses latest review state as the review stage summary and labels sub-second durations', () => {
    const events: PathScientistEvent[] = [
      {
        kind: 'state',
        ts: 200,
        status: 'completed',
        state: {
          stage: 'completed',
          latest_review: {
            status: 'not_improved',
            decision: 'enter_synthesis',
            summary: 'Stopping after 5/5 iterations; best run remains run_a with AUC 0.9638.',
          },
          stage_history: [
            { stage: 'execution', started_at: 100, ended_at: 199.5, duration_sec: 99.5 },
            { stage: 'review', started_at: 199.5, ended_at: 199.8, duration_sec: 0.3 },
            { stage: 'synthesis', started_at: 199.8, ended_at: 200, duration_sec: 0.2 },
            { stage: 'completed', started_at: 200 },
          ],
        },
      },
    ]

    const view = buildPathScientistExecutionView(null, events)
    const review = view.stages.find((stage) => stage.id === 'review')
    const synthesis = view.stages.find((stage) => stage.id === 'synthesis')

    expect(review?.summary).toBe('Stopping after 5/5 iterations; best run remains run_a with AUC 0.9638.')
    expect(review?.durationLabel).toBe('<1s')
    expect(synthesis?.durationLabel).toBe('<1s')
  })

  it('extracts the latest external test result and leaves sessions without external tests empty', () => {
    const externalRecord = {
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
    }
    const session = {
      session_id: 's-external',
      title: 'NSCLC external validation',
      question: 'Train on TCGA NSCLC and validate on external NSCLC.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'auc' },
        selected_dataset: { name: 'TCGA-NSCLC' },
        external_test_request: {
          contract: {
            datasets: [{ role: 'external', dataset_name: 'Nanfang-NSCLC' }],
          },
        },
        external_test_history: [
          { run_id: 'older_external', status: 'failed', metrics: { auc: 0.5 } },
          externalRecord,
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])
    const noExternalView = buildPathScientistExecutionView({
      ...session,
      session_id: 's-no-external',
      state: { objective: { success_metric: 'auc' } },
      events: [],
    }, [])

    expect(view.runSummary.externalTest).toMatchObject({
      runId: 'external_run_001',
      status: 'completed',
      committed: true,
      modelPath: '/workspace/outputs/best_model.pt',
      runDir: '/workspace/runs/external_run_001',
      primaryMetric: { name: 'auc', value: 0.91342 },
      sampleCount: 18,
      datasetName: 'Nanfang-NSCLC',
    })
    expect(noExternalView.runSummary.externalTest).toBeNull()
  })

  it('extracts internal test metrics from the committed training run when external validation also exists', () => {
    const session = {
      session_id: 's-internal-and-external',
      title: 'NSCLC internal and external validation',
      question: 'Train on TCGA NSCLC and validate internally and externally.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'auc' },
        selected_dataset: { name: 'TCGA-NSCLC' },
        external_test_request: {
          external_data: { dataset_name: 'Nanfang-NSCLC' },
          contract: {
            datasets: [{ role: 'external', dataset_name: 'Nanfang-NSCLC' }],
          },
        },
        best_run_id: 'run_train',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_train',
            committed: true,
            model_path: '/workspace/output/runs/run_train/best_model.pth',
            run_dir: '/workspace/output/runs/run_train',
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
              external_validation: {
                auc: 0.5556,
                accuracy: 0.6667,
                n: 6,
              },
            },
          },
        ],
        external_test_history: [
          {
            run_id: 'run_external',
            status: 'completed',
            committed: false,
            metrics: {
              auc: 0.5556,
              accuracy: 0.6667,
              n_external_evaluated: 6,
            },
          },
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect(view.runSummary.internalTest).toMatchObject({
      runId: 'run_train',
      status: 'completed',
      committed: true,
      modelPath: '/workspace/output/runs/run_train/best_model.pth',
      runDir: '/workspace/output/runs/run_train',
      primaryMetric: { name: 'auc', value: null },
      sampleCount: 1,
      coverage: 1,
      missingFeatureCount: 0,
      datasetName: 'TCGA-NSCLC',
    })
    expect(view.runSummary.externalTest).toMatchObject({
      datasetName: 'Nanfang-NSCLC',
      runId: 'run_external',
      primaryMetric: { name: 'auc', value: 0.5556 },
      sampleCount: 6,
    })
  })

  it('extracts internal test metrics from current training metrics.test records', () => {
    const session = {
      session_id: 'aa15b0a18b04',
      title: 'Chronic gastritis with external validation',
      question: 'Use Chronic-gastritis as internal and PWH-GC-IM as external.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'auc' },
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
                precision: 0.7732,
                recall: 0.9294,
              },
              data_coverage: {
                usable_counts: { train: 568, val: 111, test: 114 },
                missing_feature_counts: { train: 4, val: 3, test: 0 },
              },
              split_counts: { train: 568, val: 111, test: 114 },
            },
          },
        ],
        external_test_history: [
          {
            run_id: 'run_70546e4d',
            status: 'completed',
            metrics: {
              auc: 0.7256,
              accuracy: 0.7838,
              coverage: { n_external_evaluated: 2697 },
            },
          },
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect(view.runSummary.internalTest).toMatchObject({
      runId: 'run_36962082',
      primaryMetric: { name: 'auc', value: 0.9757 },
      sampleCount: 114,
      missingFeatureCount: 0,
    })
    expect(view.runSummary.externalTest?.primaryMetric).toEqual({ name: 'auc', value: 0.7256 })
  })

  it('keeps internal classification display on AUC when objective metric is external AUC', () => {
    const session = {
      session_id: 'f79dee7f81b0',
      title: 'NSCLC internal and external validation',
      question: 'Train on TCGA NSCLC and validate internally and externally.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'external_auc' },
        best_run_id: 'run_train',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_train',
            committed: true,
            metrics: {
              internal_test: {
                accuracy: 0,
                auc: null,
                n: 1,
                coverage: 1,
                missing_feature_count: 0,
              },
            },
          },
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect(view.runSummary.internalTest?.primaryMetric).toEqual({ name: 'auc', value: null })
  })

  it('uses external metrics embedded in the committed run history when no external history exists', () => {
    const session = {
      session_id: 's-run-history-external',
      title: 'NSCLC external validation from run metrics',
      question: 'Train on TCGA NSCLC and validate on external NSCLC.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'auc' },
        best_run_id: 'run_best',
        run_history: [
          {
            iteration: 0,
            run_id: 'run_best',
            committed: true,
            model_path: '/workspace/outputs/best_model.pt',
            run_dir: '/workspace/output/runs/run_best',
            metrics: {
              test: { auc: 0.88 },
              external_test: {
                auc: 0.9421,
                accuracy: 0.875,
                n_external_evaluated: 4,
              },
            },
          },
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect(view.runSummary.externalTest).toMatchObject({
      runId: 'run_best',
      status: 'completed',
      committed: true,
      modelPath: '/workspace/outputs/best_model.pt',
      runDir: '/workspace/output/runs/run_best',
      primaryMetric: { name: 'auc', value: 0.9421 },
      sampleCount: 4,
    })
  })

  it('normalizes prefixed external metric names for display', () => {
    const session = {
      session_id: 's-external-prefixed-metric',
      title: 'NSCLC external validation',
      question: 'Train on TCGA NSCLC and validate externally.',
      status: 'completed',
      stage: 'completed',
      state: {
        objective: { success_metric: 'external_auc' },
        external_test_history: [
          {
            run_id: 'run_external',
            status: 'completed',
            metrics: {
              external_auc: 0.5556,
              auc: 0.5556,
              accuracy: 0.6667,
              external: {
                auc: 0.5556,
                accuracy: 0.6667,
              },
            },
          },
        ],
      },
      events: [],
    } satisfies PathScientistSessionDetail

    const view = buildPathScientistExecutionView(session, [])

    expect(view.runSummary.externalTest?.primaryMetric).toEqual({ name: 'auc', value: 0.5556 })
  })
})
