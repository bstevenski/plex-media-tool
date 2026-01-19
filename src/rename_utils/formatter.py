"""
Filename formatter for creating Plex-compliant media file names.

This module provides functions to format media filenames according to
Plex naming conventions for both movies and TV shows.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from common.constants import MEDIA_BASE_FOLDER

logger = logging.getLogger(__name__)


def _sanitize_filename(text: str) -> str:
    """Remove characters that are problematic in filenames."""
    invalid_chars = r'[<>:"/\\|?*]'
    return re.sub(invalid_chars, "", text).strip()


def _is_show_still_running(tmdb_data: dict) -> bool:
    """
    Check if a TV show is still running based on TMDB data.

    A show is considered "still running" if:
    1. It has a first air date in the current year or within the last ~2 years
    2. OR it doesn't have an end date listed

    This follows Plex conventions where currently running shows use YYYY format
    and ended shows use YYYY-YYYY format.
    """
    current_date = datetime.now()
    current_year = current_date.year

    # Check if show is recent (within last 2 years)
    first_air_date = tmdb_data.get("first_air_date")
    if first_air_date:
        try:
            air_date = datetime.fromisoformat(first_air_date)
            years_since_air = current_year - air_date.year
            if years_since_air <= 2:
                return True
        except (ValueError, TypeError):
            # Invalid date format, assume it's older
            return True

    # Check if show has an end date
    end_date_str = tmdb_data.get("end_date")
    if end_date_str:
        try:
            end_date = datetime.fromisoformat(end_date_str)
            if end_date > current_date:
                return False
        except (ValueError, TypeError):
            pass

    # If no explicit end date, assume it's still running
    return True


### Internal helper functions ###
def _format_movie_filename(title: str, year: int, tmdb_id: int, extension: str) -> str:
    """
    Format a movie filename according to Plex conventions.

    Example: "Wake Up Dead Man A Knives Out Mystery (2025) {tmdb-812583}.mkv"
    """
    # Clean title, sanitize, and ensure proper spacing
    clean_title = " ".join(title.split())
    clean_title = _sanitize_filename(clean_title)

    # Format: Title (Year) {tmdb-id}.ext
    filename = f"{clean_title} ({year}) {{tmdb-{tmdb_id}}}{extension}"

    logger.debug(f"Formatted movie filename: {filename}")
    return filename


def _format_episode_filename(
        series_title: str,
        season: int,
        episode: int,
        episode_title: Optional[str],
        extension: str
) -> str:
    """
    Format a TV show episode filename according to Plex conventions.
    Format: "Series Title - SXXEXX - Episode Title.ext"
    Example: "It's Always Sunny in Philadelphia - S01E06 - The Gang Finds a Dead Guy.mkv"

    If episode_title is None or empty, uses "Episode XX" as fallback.
    """
    # Clean and sanitize titles to remove invalid filesystem characters
    clean_title = " ".join(series_title.split())
    clean_title = _sanitize_filename(clean_title)

    season_str = f"{season:02d}"
    episode_str = f"{episode:02d}"

    # Handle missing episode title with fallback
    if not episode_title or not episode_title.strip():
        clean_episode_title = f"Episode {episode_str}"
        logger.warning(f"Missing episode title, using fallback: {clean_episode_title}")
    else:
        clean_episode_title = " ".join(episode_title.split())
        clean_episode_title = _sanitize_filename(clean_episode_title)

    filename = f"{clean_title} - S{season_str}E{episode_str} - {clean_episode_title}{extension}"

    logger.debug(f"Formatted TV filename: {filename}")
    return filename


def _format_movie_folder_name(title: str, year: int, tmdb_id: int) -> str:
    """
    Format a movie folder name according to Plex conventions.

    Example: "Batman Begins (2005) {imdb-tt0372784}"
    """
    # Clean and sanitize title to remove invalid filesystem characters
    clean_title = " ".join(title.split())
    clean_title = _sanitize_filename(clean_title)

    # Use TMDB ID for consistency (Plex prefers TMDB over IMDB)
    folder_name = f"{clean_title} ({year}) {{tmdb-{tmdb_id}}}"

    logger.debug(f"Formatted movie folder name: {folder_name}")
    return folder_name


def _format_tv_show_folder_name(title: str, year: Optional[int], tmdb_id: int, is_ongoing: bool = False) -> str:
    """
    Format a TV show folder name according to Plex conventions.

    Examples:
        "It's Always Sunny in Philadelphia (2005-) {tmdb-2710}" (ended show)
        "The Simpsons (1989-) {tmdb-456}" (ongoing show)
    """
    # Clean and sanitize title to remove invalid filesystem characters
    clean_title = " ".join(title.split())
    clean_title = _sanitize_filename(clean_title)

    if is_ongoing:
        # For currently running shows, use YYYY format: Show Name (YYYY-) {tmdb-id}
        folder_name = f"{clean_title} ({year}-) {{tmdb-{tmdb_id}}}"
    elif year:
        # For ended shows, use YYYY-YYYY format: Show Name (YYYY-YYYY) {tmdb-id}
        folder_name = f"{clean_title} ({year}-) {{tmdb-{tmdb_id}}}"
    else:
        # For shows without clear year info, use just TMDB ID
        folder_name = f"{clean_title} {{tmdb-{tmdb_id}}}"

    logger.debug(f"Formatted TV show folder name: {folder_name}")
    return folder_name


def _format_season_folder_name(season: int) -> str:
    """
    Format a season folder name according to Plex conventions.

    Example: "Season 01"
    """
    season_str = f"{season:02d}"
    folder_name = f"Season {season_str}"

    logger.debug(f"Formatted season folder name: {folder_name}")
    return folder_name


### Public functions ###
def construct_movie_path(
        title: str,
        year: int,
        tmdb_id: int,
        extension: str,
) -> Path:
    """Construct the full path for a movie file."""
    # Create movie folder name
    movie_folder_name = _format_movie_folder_name(title, year, tmdb_id)
    # Create movie filename
    filename = _format_movie_filename(title, year, tmdb_id, extension)
    # Return path: /Movies/Movie Name (Year) {tmdb-id}/Movie Name (Year) {tmdb-id}.ext
    return Path(MEDIA_BASE_FOLDER, 'Movies') / movie_folder_name / filename


def construct_tv_show_path(
        title: str,
        year: Optional[int],
        tmdb_id: int,
        season: int,
        episode: int,
        episode_title: Optional[str],
        extension: str,
        use_episode_title_only: bool = False,
) -> Path:
    # Create show folder
    show_folder_name = _format_tv_show_folder_name(title, year, tmdb_id)
    show_folder = Path(MEDIA_BASE_FOLDER, 'TV Shows') / show_folder_name

    # Create season folder
    season_folder_name = _format_season_folder_name(season)
    season_folder = show_folder / season_folder_name

    # Create filename
    filename = _format_episode_filename(title, season, episode, episode_title, extension)

    return season_folder / filename
