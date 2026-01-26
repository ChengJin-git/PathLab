"""
Port Discovery Utilities for PathLab Services

Provides automatic port discovery to avoid conflicts when running multiple services.
"""

import socket
import sys


def find_free_port() -> int:
    """
    Find and return an available port on the system.
    
    Uses socket binding with port 0 to let the OS assign an available port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def announce_port(port: int, service_name: str = "service") -> None:
    """
    Announce the port number to stdout for Electron to capture.
    
    Format: PORT=<port>
    This is parsed by sidecar-manager.ts to discover service ports.
    
    Args:
        port: The port number to announce
        service_name: Name of the service (for logging)
    """
    # Print in a format that Electron can parse
    print(f"PORT={port}", flush=True)
    print(f"[{service_name}] Starting on port {port}", flush=True)
    sys.stdout.flush()


def get_port_from_env_or_auto(env_var: str, default_port: int = 0) -> int:
    """
    Get port from environment variable or auto-discover.
    
    Args:
        env_var: Environment variable name to check
        default_port: Default port if env var is set to 0 or not set
        
    Returns:
        Port number to use
    """
    import os
    port_str = os.environ.get(env_var, "")
    
    if port_str and port_str != "0":
        try:
            return int(port_str)
        except ValueError:
            pass
    
    if default_port != 0:
        return default_port
    
    return find_free_port()

