#!/usr/bin/env python3
"""Root-level CLI entry point — `python cli.py <url> [options]`"""
import sys
from site_downloader.cli import main

if __name__ == "__main__":
    sys.exit(main())
