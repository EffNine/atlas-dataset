"""Simple CSV record parser with a known off-by-one bug."""


class CSVParser:
    """Parse CSV-formatted text into records."""

    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def split_records(self, text: str) -> list[dict[str, str]]:
        """
        Split CSV text into a list of record dictionaries.

        BUG: The range stops one element early, skipping the last record.
        """
        lines = text.strip().split("\n")
        if not lines:
            return []

        headers = [h.strip() for h in lines[0].split(self.delimiter)]
        records = []

        for i in range(1, len(lines) - 1):  # BUG: should be len(lines)
            values = [v.strip() for v in lines[i].split(self.delimiter)]
            if len(values) == len(headers):
                records.append(dict(zip(headers, values)))

        return records

    def get_field(self, records: list[dict[str, str]], field: str) -> list[str]:
        """Extract a single field from all records."""
        return [r.get(field, "") for r in records]
