#!/usr/bin/env python3
"""Verify debug mode configuration and exception handler."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from app.core.config import get_settings

def main():
    settings = get_settings()

    print("Configuration Verification:")
    print(f"  debug_mode: {settings.debug_mode}")
    print(f"  api_name: {settings.api_name}")
    print(f"  api_version: {settings.api_version}")

    # Test exception handler import
    try:
        from app.core.exception_handlers import global_exception_handler
        print("\n✓ Exception handler imported successfully")
    except ImportError as e:
        print(f"\n✗ Failed to import exception handler: {e}")
        return 1

    # Test main app import
    try:
        from app.main import app
        print("✓ Main app imported successfully")

        # Check if exception handler is registered
        exception_handlers = app.exception_handlers
        if Exception in exception_handlers:
            print("✓ Global exception handler is registered")
        else:
            print("✗ Global exception handler is NOT registered")
            return 1
    except ImportError as e:
        print(f"✗ Failed to import main app: {e}")
        return 1

    print("\n✓ All checks passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
