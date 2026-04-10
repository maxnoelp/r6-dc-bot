"""
r6api/client.py — Async HTTP client for the R6Data REST API.

Base URL: https://api.r6data.eu
Authentication: "api-key" request header.

Endpoints used:
- GET /api/stats?type=accountInfo  — profile lookup
- GET /api/stats?type=stats        — cumulative ranked stats
- GET /api/stats?type=operatorStats — per-operator stats
"""

import logging
import urllib.parse
import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

# Normalise platform aliases so users can type "ubisoft" or "pc"
_PLATFORM_ALIASES: dict[str, str] = {
    "ubisoft": "uplay",
    "pc":      "uplay",
    "ps4":     "psn",
    "ps5":     "psn",
    "xbox":    "xbl",
}

# Maps platformType to the platform_families value required by the API
_RANK_NAMES: list[str] = [
    "Unranked",
    "Copper 5", "Copper 4", "Copper 3", "Copper 2", "Copper 1",
    "Bronze 5", "Bronze 4", "Bronze 3", "Bronze 2", "Bronze 1",
    "Silver 5", "Silver 4", "Silver 3", "Silver 2", "Silver 1",
    "Gold 5",   "Gold 4",   "Gold 3",   "Gold 2",   "Gold 1",
    "Platinum 5","Platinum 4","Platinum 3","Platinum 2","Platinum 1",
    "Emerald 5","Emerald 4","Emerald 3","Emerald 2","Emerald 1",
    "Diamond 5","Diamond 4","Diamond 3","Diamond 2","Diamond 1",
    "Champion",
]


def _rank_name(rank_id: int) -> str:
    if 0 <= rank_id < len(_RANK_NAMES):
        return _RANK_NAMES[rank_id]
    return f"Rank {rank_id}"


_PLATFORM_FAMILIES: dict[str, str] = {
    "uplay": "pc",
    "psn":   "psn",
    "xbl":   "xbl",
}


def _normalise_platform(platform: str) -> str:
    p = platform.lower().strip()
    return _PLATFORM_ALIASES.get(p, p)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class AccountInfo(BaseModel):
    profileId: str
    nameOnPlatform: str
    platformType: str
    profilePicture: str = ""


class PlayerStats(BaseModel):
    kills: int
    deaths: int
    wins: int
    losses: int
    rankPoints: int
    rank: str


class OperatorStat(BaseModel):
    name: str
    roundsPlayed: int
    roundsWon: int
    iconUrl: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class R6DataClient:
    """Thin async wrapper around the R6Data REST API."""

    BASE_URL = "https://api.r6data.eu"

    def __init__(self, api_key: str) -> None:
        self._headers = {"api-key": api_key, "Content-Type": "application/json"}
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=self._headers,
            timeout=15.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        response = await self._client.get(path, params=params)
        log.info("R6Data URL=%s params=%s → %d: %s", response.request.url, params, response.status_code, response.text[:500])
        if response.status_code != 200:
            raise ValueError(
                f"R6Data API error {response.status_code} for {path}: {response.text}"
            )
        return response.json()

    async def get_account_info(self, username: str, platform: str = "uplay") -> AccountInfo:
        platform = _normalise_platform(platform)
        data = await self._get(
            "/api/stats",
            params={
                "type": "accountInfo",
                "nameOnPlatform": username,
                "platformType": platform,
                "platform_families": _PLATFORM_FAMILIES.get(platform, "pc"),
            },
        )
        log.debug("accountInfo raw: %s", data)

        if not isinstance(data, dict):
            raise ValueError(f"No R6 account found for '{username}' on {platform}.")

        # Extract profile ID from the avatar URL (e.g. .../e0cd91e4-.../default...)
        profile_id = ""
        pic_url: str = data.get("profilePicture", "")
        if pic_url:
            parts = [p for p in pic_url.split("/") if len(p) == 36 and p.count("-") == 4]
            if parts:
                profile_id = parts[0]

        # Find the matching platform entry in the profiles list
        profiles: list = data.get("profiles", [])
        matched_name = username
        matched_platform = platform
        for p in profiles:
            if p.get("platformType") == platform:
                matched_name = p.get("nameOnPlatform", username)
                matched_platform = p.get("platformType", platform)
                break

        if not profiles and not profile_id:
            raise ValueError(f"No R6 account found for '{username}' on {platform}.")

        return AccountInfo(
            profileId=profile_id or username,
            nameOnPlatform=matched_name,
            platformType=matched_platform,
            profilePicture=pic_url,
        )

    async def get_player_stats(self, username: str, platform: str = "uplay") -> PlayerStats:
        platform = _normalise_platform(platform)
        data = await self._get(
            "/api/stats",
            params={
                "type": "stats",
                "nameOnPlatform": username,
                "platformType": platform,
                "platform": platform,
                "platform_families": _PLATFORM_FAMILIES.get(platform, "pc"),
            },
        )

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected stats response type: {type(data)}")

        # Navigate: platform_families_full_profiles → board_ids_full_profiles → ranked
        try:
            board_profiles = (
                data["platform_families_full_profiles"][0]["board_ids_full_profiles"]
            )
            ranked_entry = next(
                (b for b in board_profiles if b.get("board_id") == "ranked"), None
            )
            if ranked_entry is None:
                raise ValueError("No ranked board found in stats response.")

            full = ranked_entry["full_profiles"][0]
            profile = full["profile"]
            season_stats = full["season_statistics"]
            outcomes = season_stats.get("match_outcomes", {})

            return PlayerStats(
                kills=int(season_stats.get("kills", 0)),
                deaths=int(season_stats.get("deaths", 0)),
                wins=int(outcomes.get("wins", 0)),
                losses=int(outcomes.get("losses", 0)),
                rankPoints=int(profile.get("rank_points", 0)),
                rank=_rank_name(int(profile.get("rank", 0))),
            )
        except (KeyError, IndexError, StopIteration) as exc:
            raise ValueError(f"Unexpected stats response structure: {exc}") from exc

    async def get_operator_stats(self, username: str, platform: str = "uplay") -> list[OperatorStat]:
        platform = _normalise_platform(platform)
        data = await self._get(
            "/api/stats",
            params={
                "type": "operatorStats",
                "nameOnPlatform": username,
                "platformType": platform,
            },
        )

        if not isinstance(data, dict):
            return []

        operators_list = data.get("operators", [])
        result: list[OperatorStat] = [
            OperatorStat(
                name=op.get("operator", "Unknown"),
                roundsPlayed=int(op.get("roundsPlayed", 0)),
                roundsWon=int(op.get("wins", 0)),
                iconUrl=f"https://r6data.eu/assets/img/operators/{urllib.parse.quote(op.get('operator', 'unknown').lower())}.png",
            )
            for op in operators_list
            if int(op.get("roundsPlayed", 0)) > 0
        ]
        result.sort(key=lambda o: o.roundsPlayed, reverse=True)
        return result
