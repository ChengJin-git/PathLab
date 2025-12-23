"""
PathStudio Python Sidecar - Unified Entry Point

This script is the main entry point for the Python backend,
started by Electron's sidecar-manager.

It launches the Gateway service with dynamic port discovery.
Gateway integrates all backend functionality (WSI processing, AI, etc.)
"""

import os
import sys
import signal
import subprocess
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from backend.common.port_utils import find_free_port, announce_port


def main():
    """Main entry point for PathStudio Python backend"""
    # Handle graceful shutdown
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(0))

    # Find available ports for all services
    gateway_port = find_free_port()
    preprocessing_port = find_free_port()
    ai_port = find_free_port()

    # Announce Gateway port first (this is what Electron reads)
    # Format: PORT=<port> - Electron parses this line
    announce_port(gateway_port, "Gateway")

    # Set environment variables for service discovery
    os.environ["GATEWAY_PORT"] = str(gateway_port)
    os.environ["PREPROCESSING_PORT"] = str(preprocessing_port)
    os.environ["AI_PORT"] = str(ai_port)
    os.environ["PREPROCESSING_SERVICE_URL"] = f"http://127.0.0.1:{preprocessing_port}"
    os.environ["AI_SERVICE_URL"] = f"http://127.0.0.1:{ai_port}"

    print(f"[Services] Gateway: {gateway_port}, Preprocessing: {preprocessing_port}, AI: {ai_port}", flush=True)

    # Start services
    # For simplicity, we run Gateway directly with uvicorn
    # In production, this would spawn all three services
    import uvicorn

    # Import and run Gateway app
    # The Gateway already imports and initializes the database
    uvicorn.run(
        "gateway.main:app",
        host="127.0.0.1",
        port=gateway_port,
        log_level="info",
        # Disable reload in production, enable in dev
        reload=os.environ.get("PATHSTUDIO_DEV", "0") == "1"
    )


if __name__ == "__main__":
    main()
