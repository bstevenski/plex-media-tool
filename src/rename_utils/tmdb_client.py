"""
TMDb API client for fetching movie and TV show metadata.

This module provides a clean interface to The Movie Database API,
handling search requests, error handling, and response parsing.
"""

import logging
from typing import Dict, List, Optional, Any

import requests

from common.constants import TMDB_API_KEY, TMDB_BASE_URL

logger = logging.getLogger(__name__)


class TMDbError(Exception):
    """Base exception for TMDb API errors."""

    pass


class TMDbAPIError(TMDbError):
    """Exception for API request failures."""

    pass


class TMDbNotFoundError(TMDbError):
    """Exception for when content is not found."""

    pass


class TMDbClient:
    """Client for interacting with The Movie Database API."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the TMDb client with an API key."""
        self.api_key = api_key or TMDB_API_KEY
        if not self.api_key:
            raise TMDbError("TMDb API key is required. Set TMDB_API_KEY environment variable.")

        self.session = requests.Session()
        self.session.params = {"api_key": self.api_key}

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the TMDb API and handle errors."""
        url = f"{TMDB_BASE_URL}/{endpoint.lstrip('/')}"

        try:
            logger.debug(f"TMDb API request: {url}")
            if params:
                # Redact API key for logging
                safe_params = {k: v for k, v in params.items() if k != "api_key"}
                logger.debug(f"Request params: {safe_params}")

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if "success" in data and not data["success"]:
                logger.error(f"❌ TMDb API error: {data.get('status_message', 'Unknown error')}")
                raise TMDbAPIError(f"TMDb API error: {data.get('status_message', 'Unknown error')}")

            # Log response summary (not full data to avoid spam)
            if "results" in data:
                logger.debug(f"TMDb response: {len(data['results'])} results found")
            else:
                logger.debug(f"TMDb response: success")

            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"TMDb request failed: {e}")
            raise TMDbAPIError(f"Request failed: {e}")
        except ValueError as e:
            logger.error(f"TMDb JSON decode failed: {e}")
            raise TMDbAPIError(f"Invalid JSON response: {e}")

    def search_movie(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search for movies by title and optionally year."""
        params = {"query": title}
        if year:
            params["year"] = str(year)

        logger.info(f"Searching TMDb for movie: '{title}' ({year})")
        data = self._make_request("search/movie", params)
        results = data.get("results", [])
        logger.info(f"TMDb returned {len(results)} movie results")

        # Log top results for debugging
        if results:
            logger.debug(f"Top TMDb movie results:")
            for i, result in enumerate(results[:3]):
                logger.debug(
                    f"  {i + 1}. {result.get('title')} ({result.get('release_date', 'Unknown')}) - ID: {result.get('id')}"
                )
        else:
            logger.warning(f"No TMDb movie results found for: '{title}' ({year})")

        return results

    def search_tv_show(self, title: str, first_air_date_year: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search for TV shows by title and optionally first air date year."""
        params = {"query": title}
        if first_air_date_year:
            params["first_air_date_year"] = str(first_air_date_year)

        logger.info(f"Searching TMDb for TV show: '{title}' ({first_air_date_year})")
        data = self._make_request("search/tv", params)
        results = data.get("results", [])
        logger.info(f"TMDb returned {len(results)} TV show results")

        # Log top results for debugging
        if results:
            logger.debug(f"Top TMDb TV results:")
            for i, result in enumerate(results[:3]):
                logger.debug(
                    f"  {i + 1}. {result.get('name')} ({result.get('first_air_date', 'Unknown')}) - ID: {result.get('id')}"
                )
        else:
            logger.warning(f"No TMDb TV results found for: '{title}' ({first_air_date_year})")

        return results

    def get_movie_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Get detailed information for a specific movie."""
        logger.debug(f"Getting movie details for ID: {tmdb_id}")
        return self._make_request(f"movie/{tmdb_id}")

    def get_tv_show_details(self, tmdb_id: int) -> Dict[str, Any]:
        """Get detailed information for a specific TV show."""
        logger.debug(f"Getting TV show details for ID: {tmdb_id}")
        return self._make_request(f"tv/{tmdb_id}")

    def get_tv_episode_details(self, tmdb_id: int, season_number: int, episode_number: int,
                               episode_title: Optional[str] = "") -> Dict[str, Any]:
        """Get detailed information for a specific TV episode.

        Returns episode data with season_number and episode_number fields that reflect
        the actual episode found (useful when searching by title across seasons).
        """
        original_season = season_number
        original_episode = episode_number

        if episode_title != "":
            logger.debug(f"Getting episode details for show ID {tmdb_id} with title '{episode_title}'")
            # Search for episode by title within the season
            season_data = self._make_request(f"tv/{tmdb_id}/season/{season_number}")
            episodes = season_data.get("episodes", [])
            for episode in episodes:
                if episode.get("name", "").lower() == episode_title.lower():
                    episode_number = episode.get("episode_number")
                    logger.debug(f"Found episode '{episode_title}' as S{season_number}E{episode_number}")
                    break
            else:
                logger.error(
                    f"Episode titled '{episode_title}' not found in season {original_season} of show ID {tmdb_id}, searching all seasons...")
                # If not found in the specified season, search all seasons
                tv_data = self.get_tv_show_details(tmdb_id)
                for season in tv_data.get("seasons", []):
                    season_num = season.get("season_number")
                    season_data = self._make_request(f"tv/{tmdb_id}/season/{season_num}")
                    episodes = season_data.get("episodes", [])
                    for episode in episodes:
                        if episode.get("name", "").lower() == episode_title.lower():
                            episode_number = episode.get("episode_number")
                            season_number = season_num
                            logger.debug(f"Found episode '{episode_title}' as S{season_number}E{episode_number}")
                            break
                    else:
                        continue
                    break
        logger.debug(f"Getting episode details for show ID {tmdb_id}, S{season_number}E{episode_number}")
        episode_data = self._make_request(f"tv/{tmdb_id}/season/{season_number}/episode/{episode_number}")

        # Include the corrected season and episode numbers in the response
        episode_data["season_number"] = season_number
        episode_data["episode_number"] = episode_number

        return episode_data

    def find_best_movie_match(self, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Find the best matching movie for a given title and year."""
        results = self.search_movie(title, year)

        if not results:
            logger.warning(f"No TMDb results found for movie: '{title}' ({year})")
            # Try alternative search without year
            if year:
                logger.info(f"Retrying movie search without year filter: '{title}'")
                results = self.search_movie(title, None)
                if results:
                    result = results[0]
                    logger.info(
                        f"Using best match (no year): '{result.get('title')}' ({result.get('release_date')}) - ID: {result.get('id')}"
                    )
                    return result
            return None

        # If we have a Year, prefer exact year matches
        if year:
            exact_matches = [r for r in results if r.get("release_date", "").startswith(str(year))]
            if exact_matches:
                result = exact_matches[0]
                logger.info(f"Found exact year match: '{result.get('title')}' ({result.get('release_date')})")
                return result

        # Return the first (highest rated) result
        result = results[0]
        logger.info(
            f"Using best match: '{result.get('title')}' ({result.get('release_date')}) - ID: {result.get('id')}"
        )
        return result

    def find_best_tv_match(self, title: str, year: Optional[int] = None, use_episode_titles: bool = False) -> Optional[Dict[str, Any]]:
        """Find the best matching TV show for a given title and year.

        Args:
            title: The TV show title to search for
            year: Optional year of first air date
            use_episode_titles: Whether to prioritize episode titles in matching (reserved for future use)

        Returns:
            The best matching TV show result or None if not found
        """
        results = self.search_tv_show(title, year)

        if not results:
            logger.warning(f"No TMDb results found for TV show: '{title}' ({year})")

            # Try alternative search strategies
            alternative_titles = [
                title.replace(" US", ""),  # Remove region suffix
                title.replace(" (US)", ""),
                title.replace(" UK", ""),
                title.replace(" (UK)", ""),
                title.replace(" ", ""),  # Remove spaces
            ]

            for alt_title in alternative_titles:
                if alt_title != title:
                    logger.info(f"Trying alternative title: '{alt_title}'")
                    results = self.search_tv_show(alt_title, year)
                    if results:
                        result = results[0]
                        logger.info(
                            f"Found match with alternative title: '{result.get('name')}' ({result.get('first_air_date')}) - ID: {result.get('id')}"
                        )
                        return result

            # Try without year filter
            if year:
                logger.info(f"Retrying TV search without year filter: '{title}'")
                results = self.search_tv_show(title, None)
                if results:
                    result = results[0]
                    logger.info(
                        f"Using best match (no year): '{result.get('name')}' ({result.get('first_air_date')}) - ID: {result.get('id')}"
                    )
                    return result

            return None

        # If we have a Year, prefer exact year matches
        if year:
            exact_matches = [r for r in results if r.get("first_air_date", "").startswith(str(year))]
            if exact_matches:
                result = exact_matches[0]
                logger.info(f"Found exact year match: '{result.get('name')}' ({result.get('first_air_date')})")
                return result

        # Return the first (highest rated) result
        result = results[0]
        logger.info(
            f"Using best match: '{result.get('name')}' ({result.get('first_air_date')}) - ID: {result.get('id')}"
        )
        return result

    def get_episode_info(self, tmdb_id: int, season_number: int, episode_number: int, episode_title: Optional[str],
                         use_episode_title: bool = False) -> Optional[Dict[str, Any]]:
        """Get episode information, returning None if not found."""
        try:
            if use_episode_title:
                return self.get_tv_episode_details(tmdb_id, season_number, episode_number, episode_title)
            else:
                return self.get_tv_episode_details(tmdb_id, season_number, episode_number)
        except TMDbAPIError as e:
            if "404" in str(e):
                logger.debug(f"Episode S{season_number}E{episode_number} not found for show ID {tmdb_id}")
                return None
            raise
