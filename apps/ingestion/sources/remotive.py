from apps.ingestion.base import BaseJobSource, FetchError

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(BaseJobSource):
    def __init__(self, limit: int | None = None) -> None:
        super().__init__(api_key=None)
        self._limit = limit

    @property
    def source_name(self) -> str:
        return "remotive"

    def fetch_page(self, page: int) -> dict:
        params = {}
        if self._limit is not None:
            params["limit"] = self._limit
        return self._get(API_URL, params=params)

    def parse_listings(self, raw: dict) -> list[dict]:
        jobs = raw.get("jobs")
        if jobs is None:
            raise FetchError("remotive: unexpected response shape — 'jobs' key missing")
        return jobs

    def has_next_page(self, raw: dict) -> bool:
        return False  # Remotive returns all results in a single response
