from apps.ingestion.base import BaseJobSource, FetchError

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource(BaseJobSource):
    def __init__(self, max_pages: int | None = None) -> None:
        super().__init__(api_key=None)
        self._max_pages = max_pages

    @property
    def source_name(self) -> str:
        return "arbeitnow"

    def fetch_page(self, page: int) -> dict:
        return self._get(API_URL, params={"page": page})

    def parse_listings(self, raw: dict) -> list[dict]:
        data = raw.get("data")
        if data is None:
            raise FetchError("arbeitnow: unexpected response shape — 'data' key missing")
        return data

    def has_next_page(self, raw: dict) -> bool:
        return raw.get("links", {}).get("next") is not None

    def fetch_all(self) -> list[dict]:
        return super().fetch_all(max_pages=self._max_pages)
