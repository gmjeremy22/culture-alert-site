import argparse
from pathlib import Path

from official_facility_directory import (
    DEFAULT_METRICS,
    extract_rows,
    score_rows,
    write_metrics,
)


def main():
    parser = argparse.ArgumentParser(
        description="Build capital-area institution scale metrics from the official cultural facilities directory."
    )
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_METRICS)
    args = parser.parse_args()

    rows = score_rows(extract_rows(args.workbook))
    write_metrics(rows, args.output)
    print(f"rows={len(rows)}")
    print(f"output={args.output.resolve()}")


if __name__ == "__main__":
    main()
