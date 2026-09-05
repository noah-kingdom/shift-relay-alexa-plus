#!/usr/bin/env python3
"""Simulate an external carrier system delivering new evidence.

This process is deliberately separate from the MCP server/client. It updates the
shared deterministic evidence snapshot; the next MCP verification call must
observe the change and flip the same operational loop from UNVERIFIED to VERIFIED.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from shift_relay.core import DemoVerifier


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--exception", default="missed_delivery")
    args = parser.parse_args()

    verifier = DemoVerifier(Path(args.evidence_file))
    verifier.inject_delivery_exception(args.exception)
    print(f"EXTERNAL_EVIDENCE_WRITTEN carrier_exception={args.exception} file={args.evidence_file}")


if __name__ == "__main__":
    main()
