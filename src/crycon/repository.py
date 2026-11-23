"""Read boundary for candidate storage.

Application code depends on this protocol instead of a concrete Supabase client.
Implementations may use Supabase, PostgreSQL directly, or in-memory test data.
"""

from typing import Any, Dict, List, Optional, Protocol, Sequence


Record = Dict[str, Any]


class CandidateRepository(Protocol):
    """Existing candidate read operations used by CLI, bot and future API."""

    def ping(self) -> bool: ...

    def get_candidate(self, candidate_id: int) -> Optional[Record]: ...

    def get_candidates(self, candidate_ids: Sequence[int]) -> List[Record]: ...

    def list_candidates(self, limit: int = 20, offset: int = 0) -> List[Record]: ...

    def list_profiles(self, candidate_id: int) -> List[Record]: ...

    def list_contacts(self, candidate_id: int) -> List[Record]: ...

    def list_wallets(self, candidate_id: int) -> List[Record]: ...

    def list_evidence(
        self,
        candidate_id: int,
        limit: int = 10,
    ) -> List[Record]: ...

    def list_top_candidate_ids(self, limit: int = 20) -> List[int]: ...

    def search_candidate_ids(self, query: str, limit: int = 10) -> List[int]: ...
