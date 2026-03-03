// Replay is not used in PathLab integration
export function useReplay() {
  return {
    isReplay: false,
    replayId: null,
  };
}
