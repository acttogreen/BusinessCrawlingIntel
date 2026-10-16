"""Legacy mapping builder retained as a guarded compatibility command.

Regional datasets must be generated through the ingestion project workflow.
"""


def main() -> None:
    raise SystemExit("Legacy pilot mapping generation is disabled; use the regional ingestion workflow")


if __name__ == "__main__":
    main()
