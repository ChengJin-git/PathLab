import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Checkbox } from '@renderer/components/ui/checkbox'

function CheckboxHarness({ onParentClick }: { onParentClick: () => void }) {
  const [checked, setChecked] = React.useState(false)

  return (
    <div onClick={onParentClick}>
      <Checkbox
        checked={checked}
        onCheckedChange={setChecked}
        aria-label="Select task"
      />
      <span data-testid="checked-state">{checked ? 'checked' : 'unchecked'}</span>
    </div>
  )
}

describe('Checkbox', () => {
  it('exposes true indeterminate state, label activation and uncontrolled form values', async () => {
    const user=userEvent.setup()
    const {rerender}=render(<label><Checkbox name="selection" indeterminate />Select page</label>)
    expect(screen.getByRole('checkbox')).toBePartiallyChecked()
    rerender(<label><Checkbox name="selection" />Select page</label>)
    await user.click(screen.getByText('Select page'))
    expect(screen.getByRole('checkbox')).toBeChecked()
    await user.keyboard(' ')
    expect(screen.getByRole('checkbox')).not.toBeChecked()
  })
  it('toggles without triggering parent click handlers', async () => {
    const user = userEvent.setup()
    const onParentClick = vi.fn()

    render(<CheckboxHarness onParentClick={onParentClick} />)

    await user.click(screen.getByRole('checkbox', { name: 'Select task' }))

    expect(screen.getByTestId('checked-state')).toHaveTextContent('checked')
    expect(onParentClick).not.toHaveBeenCalled()
  })
})
