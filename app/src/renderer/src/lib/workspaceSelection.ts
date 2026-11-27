export type ExecutionMode = 'standard' | 'read_only'
export interface WorkspaceSelection {
  workspaceId: string | null
  executionMode: ExecutionMode
  expertId: string | null
  enabledSkills: string[] | null
  enabledConnectors: string[] | null
}

const emptySelection = (): WorkspaceSelection => ({
  workspaceId: null,
  executionMode: 'standard',
  expertId: null,
  enabledSkills: null,
  enabledConnectors: null,
})
let selection = emptySelection()
export const WORKSPACE_CHANGED = 'pathlab:workspace-changed'
export function getWorkspaceSelection(): WorkspaceSelection {
  return selection
}
export function setWorkspaceSelection(value: WorkspaceSelection): void {
  selection = value
  window.dispatchEvent(new Event(WORKSPACE_CHANGED))
}
export function resetWorkspaceSelection(): void {
  setWorkspaceSelection(emptySelection())
}
