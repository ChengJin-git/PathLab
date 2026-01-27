#!/usr/bin/env python3
"""
Generate a secure JWT_SECRET for PathLab production deployment.

Usage:
    python scripts/generate_jwt_secret.py

This script will:
1. Generate a cryptographically secure 64-character hex string
2. Print instructions for setting it as an environment variable
3. Optionally append to .env file
"""

import secrets
import sys
from pathlib import Path


def generate_jwt_secret(length: int = 32) -> str:
    """Generate a cryptographically secure random hex string.
    
    Args:
        length: Number of random bytes (output will be 2x this in hex chars)
    
    Returns:
        64-character hex string (256 bits of entropy)
    """
    return secrets.token_hex(length)


def main():
    # Generate secret
    secret = generate_jwt_secret()
    
    print("=" * 70)
    print("PathLab JWT Secret Generator")
    print("=" * 70)
    print()
    print("Generated JWT_SECRET:")
    print()
    print(f"    {secret}")
    print()
    print("-" * 70)
    print("Setup Instructions:")
    print("-" * 70)
    print()
    print("Option 1: Environment Variable (recommended for production)")
    print()
    print("  Linux/macOS:")
    print(f'    export JWT_SECRET="{secret}"')
    print()
    print("  Windows (PowerShell):")
    print(f'    $env:JWT_SECRET="{secret}"')
    print()
    print("  Windows (CMD):")
    print(f'    set JWT_SECRET={secret}')
    print()
    print("-" * 70)
    print()
    
    # Check for .env file
    script_dir = Path(__file__).resolve().parent
    server_dir = script_dir.parent / "server"
    env_file = server_dir / ".env"
    
    print(f"Option 2: Add to .env file ({env_file})")
    print()
    
    response = input("Would you like to save to .env file? [y/N]: ").strip().lower()
    
    if response == 'y':
        # Read existing content
        existing_content = ""
        if env_file.exists():
            existing_content = env_file.read_text()
            
            # Check if JWT_SECRET already exists
            if "JWT_SECRET=" in existing_content:
                print()
                print("JWT_SECRET already exists in .env file!")
                overwrite = input("Overwrite existing value? [y/N]: ").strip().lower()
                if overwrite != 'y':
                    print("Aborted. No changes made.")
                    return
                
                # Remove existing JWT_SECRET line
                lines = existing_content.splitlines()
                lines = [l for l in lines if not l.startswith("JWT_SECRET=")]
                existing_content = "\n".join(lines)
                if existing_content and not existing_content.endswith("\n"):
                    existing_content += "\n"
        
        # Append new secret
        new_line = f'JWT_SECRET="{secret}"\n'
        with open(env_file, 'w') as f:
            f.write(existing_content + new_line)
        
        print()
        print(f"JWT_SECRET saved to {env_file}")
        print()
        print("IMPORTANT: Add .env to .gitignore to prevent committing secrets!")
    else:
        print()
        print("No changes made. Please set JWT_SECRET manually before production use.")
    
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()

