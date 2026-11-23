"""Supabase implementation of the candidate read boundary."""

from typing import Any, List, Sequence

from crycon.repository import Record


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 100))


def _unique_candidate_ids(rows: List[Record], limit: int) -> List[int]:
    candidate_ids: List[int] = []
    for row in rows:
        candidate_id = int(row["candidate_id"])
        if candidate_id not in candidate_ids:
            candidate_ids.append(candidate_id)
        if len(candidate_ids) >= limit:
            break
    return candidate_ids


class SupabaseCandidateRepository:
    """Translate candidate reads into Supabase table and RPC calls."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def ping(self) -> bool:
        self._client.table("candidates").select("id").limit(1).execute()
        return True

    def get_candidate(self, candidate_id: int) -> Record | None:
        response = (
            self._client.table("candidates")
            .select("*")
            .eq("id", candidate_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def get_candidates(self, candidate_ids: Sequence[int]) -> List[Record]:
        ordered_ids = list(dict.fromkeys(int(value) for value in candidate_ids))
        if not ordered_ids:
            return []
        response = (
            self._client.table("candidates")
            .select("*")
            .in_("id", ordered_ids)
            .execute()
        )
        by_id = {int(row["id"]): row for row in response.data or []}
        return [by_id[candidate_id] for candidate_id in ordered_ids if candidate_id in by_id]

    def list_candidates(self, limit: int = 20, offset: int = 0) -> List[Record]:
        limit = _bounded_limit(limit)
        offset = max(0, int(offset))
        response = (
            self._client.table("candidates")
            .select("*")
            .order("overall_trust_score", desc=True)
            .order("id")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return response.data or []

    def _list_related(self, table: str, candidate_id: int) -> List[Record]:
        response = (
            self._client.table(table)
            .select("*")
            .eq("candidate_id", candidate_id)
            .execute()
        )
        return response.data or []

    def list_profiles(self, candidate_id: int) -> List[Record]:
        return self._list_related("profiles", candidate_id)

    def list_contacts(self, candidate_id: int) -> List[Record]:
        return self._list_related("contacts", candidate_id)

    def list_wallets(self, candidate_id: int) -> List[Record]:
        return self._list_related("wallets", candidate_id)

    def list_evidence(self, candidate_id: int, limit: int = 10) -> List[Record]:
        response = (
            self._client.table("evidence")
            .select("*")
            .eq("candidate_id", candidate_id)
            .order("confidence", desc=True)
            .limit(_bounded_limit(limit))
            .execute()
        )
        return response.data or []

    def list_top_candidate_ids(self, limit: int = 20) -> List[int]:
        response = (
            self._client.table("candidates")
            .select("id")
            .order("overall_trust_score", desc=True)
            .limit(_bounded_limit(limit))
            .execute()
        )
        return [int(item["id"]) for item in response.data or []]

    def search_candidate_ids(self, query: str, limit: int = 10) -> List[int]:
        if not query or not query.strip():
            return []

        query = query.strip()
        limit = _bounded_limit(limit)

        wallet = (
            self._client.table("wallets")
            .select("candidate_id")
            .eq("wallet_address", query)
            .limit(1)
            .execute()
        )
        if wallet.data:
            return [int(wallet.data[0]["candidate_id"])]

        name_service = (
            self._client.table("wallets")
            .select("candidate_id")
            .eq("name_service", query)
            .limit(1)
            .execute()
        )
        if name_service.data:
            return [int(name_service.data[0]["candidate_id"])]

        profile = (
            self._client.table("profiles")
            .select("candidate_id")
            .eq("username", query)
            .limit(1)
            .execute()
        )
        if profile.data:
            return [int(profile.data[0]["candidate_id"])]

        candidate = (
            self._client.table("candidates")
            .select("id")
            .eq("main_username", query)
            .limit(1)
            .execute()
        )
        if candidate.data:
            return [int(candidate.data[0]["id"])]

        alias = (
            self._client.table("known_aliases")
            .select("candidate_id")
            .eq("alias", query.lower())
            .limit(1)
            .execute()
        )
        if alias.data:
            return [int(alias.data[0]["candidate_id"])]

        try:
            fuzzy = self._client.rpc(
                "search_candidates_fuzzy",
                {"search_query": query, "limit_rows": limit},
            ).execute()
            if fuzzy.data:
                # Migration 003 is unique; this also protects clients during rollout.
                return _unique_candidate_ids(fuzzy.data, limit)
        except Exception:
            # Databases still on migration 001 may not have the search RPC.
            pass

        candidate_ids: List[int] = []
        fallback_queries = (
            ("candidates", "id", "main_username"),
            ("candidates", "id", "display_name"),
            ("profiles", "candidate_id", "username"),
            ("contacts", "candidate_id", "value"),
            ("wallets", "candidate_id", "wallet_address"),
            ("wallets", "candidate_id", "name_service"),
        )

        for table, id_column, value_column in fallback_queries:
            if len(candidate_ids) >= limit:
                break
            request = (
                self._client.table(table)
                .select(id_column)
                .ilike(value_column, f"%{query}%")
            )
            response = request.limit(limit).execute()
            for row in response.data or []:
                candidate_id = int(row[id_column])
                if candidate_id not in candidate_ids:
                    candidate_ids.append(candidate_id)

        return candidate_ids[:limit]
