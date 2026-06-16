from __future__ import annotations

import argparse
from pathlib import Path

from .workflow import run_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eoh-thinsection",
        description="Conservative thin-section image assessment and QC workflow.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input directory containing thin-section images.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for CSV tables, report, thumbnails, and QC images.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace generated outputs in the output directory.",
    )
    parser.add_argument(
        "--max-registration-pairs",
        type=int,
        default=20,
        help="Maximum number of PPL/XPL pairs to attempt registration QC on.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_workflow(
        input_dir=args.input,
        output_dir=args.output,
        overwrite=args.overwrite,
        max_registration_pairs=args.max_registration_pairs,
    )
    print(f"processed_images: {summary.processed_images}")
    print("generated_files:")
    for path in summary.generated_files:
        print(f"- {path}")
    print("top_findings:")
    for finding in summary.top_findings[:5]:
        print(f"- {finding}")
    print("top_limitations:")
    for limitation in summary.top_limitations[:5]:
        print(f"- {limitation}")
    print("top_followups:")
    for followup in summary.top_followups[:5]:
        print(f"- {followup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
