import { useEffect, useRef } from 'react'

/** A new confirmation acts on an already mounted card, once validation is ready. */
export function useConfirmedSubmission(
  trigger: number | undefined,
  ready: boolean,
  blocked: boolean,
  submit: () => Promise<void>,
) {
  const previous = useRef(trigger)
  const pending = useRef(false)
  const submitRef = useRef(submit)
  submitRef.current = submit

  useEffect(() => {
    if (trigger === undefined) {
      pending.current = false
    } else if (previous.current !== undefined && trigger !== previous.current) {
      pending.current = true
    }
    previous.current = trigger
    if (blocked) pending.current = false
    if (pending.current && ready) {
      pending.current = false
      void submitRef.current()
    }
  }, [trigger, ready, blocked])
}
