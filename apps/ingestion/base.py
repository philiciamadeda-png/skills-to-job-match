from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FetchError(Exception):
    """Raised when an HTTP request fails after all retries."""


class BaseJobSource(ABC):
    def __init__(self, api_key: str | None = None) -> None:
        self._session = self._build_session(api_key)

    # ------------------------------------------------------------------
    # Abstract interface — each source must implement these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source, e.g. 'adzuna'."""

    @abstractmethod
    def fetch_page(self, page: int) -> dict:
        """Fetch a single page of raw results from the API."""

    @abstractmethod
    def parse_listings(self, raw: dict) -> list[dict]:
        """Extract the list of job dicts from a raw API response."""

    @abstractmethod
    def has_next_page(self, raw: dict) -> bool:
        """Return True if there are more pages to fetch."""

    # ------------------------------------------------------------------
    # Shared logic
    # ------------------------------------------------------------------

    def fetch_all(self) -> list[dict]:
        """Paginate through all results and return every raw listing."""
        listings: list[dict] = []
        page = 1
        while True:
            raw = self.fetch_page(page)
            listings.extend(self.parse_listings(raw))
            if not self.has_next_page(raw):
                break
            page += 1
        return listings

    def _get(self, url: str, params: dict | None = None) -> dict:
        """Shared HTTP GET with error handling."""
        try:
            response = self._session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            raise FetchError(f"{self.source_name}: HTTP {exc.response.status_code} for {url}") from exc
        except requests.RequestException as exc:
            raise FetchError(f"{self.source_name}: request failed — {exc}") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_session(api_key: str | None) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503],
            allowed_methods=["GET"],
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers.update({"User-Agent": "skills-to-job-match/1.0"})
        if api_key:
            session.headers.update({"Authorization": f"Bearer {api_key}"})
        return session
