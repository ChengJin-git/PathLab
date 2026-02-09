"""
PathLab Python Sidecar - Unified Entry Point

This script is the main entry point for the Python backend,
started by Electron's sidecar-manager.

It launches ALL three services:
- Gateway (6100) - Main API gateway
- Preprocessing (6101) - WSI processing, tile serving
- AI (6102) - Model training and inference

Modes:
- Debug mode (PATHLAB_DEBUG=1): Fixed ports 6100, 6101, 6102
- Normal mode: Auto-discover free ports, announce to Electron
"""

import os
import sys
import signal
import atexit
import multiprocessing
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from backend.common.port_utils import find_free_port, announce_port

# Default fixed ports for debug mode
DEFAULT_GATEWAY_PORT = 6100
DEFAULT_PREPROCESSING_PORT = 6101
DEFAULT_AI_PORT = 6102


def run_service(app_module: str, port: int, name: str):
    """Run a single uvicorn service in a subprocess"""
    import uvicorn

    print(f"[{name}] Starting on port {port}...", flush=True)
    uvicorn.run(
        app_module,
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False,  # Disable reload in subprocess
    )


def main():
    """Main entry point for PathLab Python backend"""
    # Determine mode
    debug_mode = os.environ.get("PATHLAB_DEBUG", "0") == "1"
    main_pid = os.getpid()

    if debug_mode:
        # Debug mode: use fixed ports
        gateway_port = int(os.environ.get("GATEWAY_PORT", DEFAULT_GATEWAY_PORT))
        preprocessing_port = int(os.environ.get("PREPROCESSING_PORT", DEFAULT_PREPROCESSING_PORT))
        ai_port = int(os.environ.get("AI_PORT", DEFAULT_AI_PORT))
        print("[Mode] DEBUG - Using fixed ports", flush=True)
    else:
        # Normal mode: auto-discover ports
        gateway_port = int(os.environ.get("PORT", 0)) or find_free_port()
        preprocessing_port = find_free_port()
        ai_port = find_free_port()
        print("[Mode] PRODUCTION - Using auto-discovered ports", flush=True)

    # Announce Gateway port first (this is what Electron reads)
    announce_port(gateway_port, "Gateway")

    # Set environment variables for service discovery
    os.environ["GATEWAY_PORT"] = str(gateway_port)
    os.environ["PREPROCESSING_PORT"] = str(preprocessing_port)
    os.environ["AI_PORT"] = str(ai_port)
    os.environ["PREPROCESSING_SERVICE_URL"] = f"http://127.0.0.1:{preprocessing_port}"
    os.environ["AI_SERVICE_URL"] = f"http://127.0.0.1:{ai_port}"

    print(f"[Services] Gateway: {gateway_port}, Preprocessing: {preprocessing_port}, AI: {ai_port}", flush=True)

    # Track child processes for cleanup
    processes = []

    def cleanup(signum=None, frame=None, from_atexit=False):
        """Cleanup all child processes on shutdown"""
        # Only main process should cleanup
        if os.getpid() != main_pid:
            return

        if not processes:
            return
            
        print("\n[Shutdown] Stopping all services...", flush=True)
        
        # Send SIGTERM to all processes first (parallel shutdown)
        for p in processes:
            if p.is_alive():
                print(f"[Shutdown] Terminating process {p.pid}...", flush=True)
                p.terminate()
        
        # Then wait for them to exit
        for p in processes:
            if p.is_alive():
                try:
                    p.join(timeout=2)
                except Exception:
                    pass
                
                if p.is_alive():
                    print(f"[Shutdown] Force killing process {p.pid}...", flush=True)
                    try:
                        p.kill()
                    except Exception:
                        pass
                    
        processes.clear()
        print("[Shutdown] All services stopped", flush=True)
        
        if not from_atexit:
            sys.exit(0)

    # Register signal handlers and atexit for robust cleanup
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    atexit.register(lambda: cleanup(from_atexit=True))

    # Start Preprocessing service in subprocess
    # NOTE: daemon=False allows AI service to spawn DataLoader workers (num_workers > 0)
    # Daemon processes cannot have children due to Python multiprocessing restrictions
    preprocessing_proc = multiprocessing.Process(
        target=run_service,
        name="Preprocessing",
        args=("backend.preprocessing.main:app", preprocessing_port, "Preprocessing"),
        daemon=False
    )
    preprocessing_proc.start()
    processes.append(preprocessing_proc)

    # Start AI service in subprocess
    # NOTE: daemon=False is REQUIRED for PyTorch DataLoader with num_workers > 0
    # Otherwise: "AssertionError: daemonic processes are not allowed to have children"
    ai_proc = multiprocessing.Process(
        target=run_service,
        name="AI",
        args=("backend.ai.main:app", ai_port, "AI"),
        daemon=False
    )
    ai_proc.start()
    processes.append(ai_proc)

    # Start Gateway service in subprocess (instead of main process)
    # This keeps the main process free for signal handling
    gateway_proc = multiprocessing.Process(
        target=run_service,
        name="Gateway",
        args=("gateway.main:app", gateway_port, "Gateway"),
        daemon=False
    )
    gateway_proc.start()
    processes.append(gateway_proc)

    # Main process loop just waits for signals
    print("[Main] All services started. Waiting for signal...", flush=True)
    try:
        # Keep main process alive
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # This will be caught by signal handler usually, but explicit catch is safe
        cleanup()
    except Exception as e:
        print(f"[Main] Error: {e}")
        cleanup()
    finally:
        cleanup()


if __name__ == "__main__":
    # Required for multiprocessing on Windows/macOS
    multiprocessing.freeze_support()
    main()
