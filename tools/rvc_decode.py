#!/usr/bin/env python3
"""
rvc_decode.py - Decode RV-C CAN data packets from the command line.

Usage:
  python3 tools/rvc_decode.py 1FFBD FF00FF00FF00FF00
  python3 tools/rvc_decode.py 1FFBD FF00FF00FF00FF00 1FFBE 0102030405060708
  python3 tools/rvc_decode.py 1FFBD FF00FF00FF00FF00 --source-id 61 --priority 6
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Allow importing from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rvc2mqtt.rvc import RVC_Decoder

SPEC_PATH = Path(__file__).resolve().parent.parent / "rvc2mqtt" / "rvc-spec.yml"


def build_arbitration_id(dgn: str, source_id: int, priority: int) -> int:
    return (priority << 26) | (int(dgn, 16) << 8) | source_id


def main():
    parser = argparse.ArgumentParser(
        description="Decode RV-C CAN packets using rvc-spec.yml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "pairs",
        nargs="+",
        metavar="DGN_OR_DATA",
        help="Alternating DGN and DATA pairs (e.g. 1FFBD FF00FF00FF00FF00)",
    )
    parser.add_argument(
        "--source-id",
        type=lambda x: int(x, 16),
        default=0x82,
        metavar="HEX",
        help="Source ID in hex (default: 82)",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=6,
        help="CAN priority 0-7 (default: 6)",
    )

    args = parser.parse_args()

    if len(args.pairs) % 2 != 0:
        parser.error("Arguments must be alternating DGN DATA pairs (even count required)")

    decoder = RVC_Decoder()
    decoder.load_rvc_spec(SPEC_PATH)

    pairs = list(zip(args.pairs[0::2], args.pairs[1::2]))
    for dgn, data in pairs:
        dgn = dgn.upper()
        data = data.upper()
        arb_id = build_arbitration_id(dgn, args.source_id, args.priority)
        result = decoder.rvc_decode(arb_id, data)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} {result}")


if __name__ == "__main__":
    main()
