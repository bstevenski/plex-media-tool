#!/usr/bin/env python3
"""
Plex Media Renamer: Handles file parsing, TMDb lookup, and file organization.

This script processes media files by:
- Parsing filenames to extract metadata
- Looking up TMDb metadata for movies and TV shows
- Renaming files according to Plex conventions
- Moving MP4 files directly to upload folder
- Moving non-MP4 files to transcode folder
- Handling errors gracefully
"""

import argparse
import signal
import sys
from pathlib import Path

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from common import (
    DEFAULT_LOG_LEVEL,
    LOG_DIR,
    MEDIA_BASE_FOLDER,
    RENAME_FOLDER,
    CONTENT_TYPE_MOVIES,
    CONTENT_TYPE_TV,
    TRANSCODE_FOLDER,
    UPLOAD_FOLDER,
    ERROR_FOLDER,
    scan_media_files,
    ensure_directory_exists,
    safe_move_with_backup,
    create_error_directory,
    setup_logging,
)
from rename_utils import (
    construct_movie_path,
    construct_tv_show_path,
    parse_media_file,
    TMDbClient,
    TMDbError,
)


class MediaRenamer:
    """Handles media file parsing, TMDb lookup, and file organization."""

    def __init__(
            self,
            dry_run: bool = False,
            log_level: str = DEFAULT_LOG_LEVEL,
            use_episode_titles: bool = False,
    ):
        """
        Initialize the Media Renamer.

        Args:
            dry_run: Preview changes without making modifications
            log_level: Logging level
            use_episode_titles: Trust episode titles over S##E## numbers for TV shows during TMDb lookup
        """
        self.dry_run = dry_run
        self.log_level = log_level
        self.use_episode_titles = use_episode_titles

        # Set up logging
        self.logger = setup_logging(
            log_level=log_level,
            log_dir=Path(LOG_DIR),
            enable_console=True,
        )

        # Initialize TMDb client
        try:
            self.tmdb_client = TMDbClient()
        except TMDbError as e:
            self.logger.error(f"Failed to initialize TMDb client: {e}")
            sys.exit(1)

        # Set up signal handlers for graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (AttributeError, OSError):
            pass

        self.logger.info("Media Renamer initialized", dry_run=dry_run)

    def _signal_handler(self, signum, _frame):
        """Handle shutdown signals gracefully."""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def run(self, source_dir: str | None = None) -> None:
        """Run the main renaming pipeline."""
        if source_dir:
            queue_dir = Path(source_dir).resolve()
        else:
            queue_dir = Path(MEDIA_BASE_FOLDER) / RENAME_FOLDER

        self.logger.info(f"Starting media renaming from: {queue_dir}")

        # Ensure all required directories exist
        self._setup_directories()

        # Initialize counters for final summary
        total_files_processed = 0
        total_files_successful = 0
        total_files_failed = 0
        mp4_files_moved = 0
        non_mp4_files_moved = 0

        # Process each content type
        try:
            for content_type in [CONTENT_TYPE_MOVIES, CONTENT_TYPE_TV]:
                content_queue_dir = queue_dir / content_type

                if not content_queue_dir.exists():
                    self.logger.debug(f"Queue directory does not exist: {content_queue_dir}")
                    continue

                self.logger.info(f"Processing {content_type} from: {content_queue_dir}")

                for filepath in scan_media_files(content_queue_dir):
                    if not self.running:
                        break

                    total_files_processed += 1

                    try:
                        success = self._process_file(filepath, content_type)
                        if success:
                            # If processing succeeded, check what type of file it was
                            # We need to track this differently since move success doesn't tell us file type
                            extension = filepath.suffix.lower()
                            if extension == ".mp4":
                                mp4_files_moved += 1
                            else:
                                non_mp4_files_moved += 1
                            total_files_successful += 1
                        else:
                            total_files_failed += 1

                    except Exception as e:
                        self.logger.error(f"Failed to process file {filepath}: {e}")
                        self._handle_error(filepath, str(e))
                        total_files_failed += 1

        except KeyboardInterrupt:
            self.logger.info("Processing interrupted by user")
        except Exception as e:
            self.logger.error(f"Processing failed: {e}")
            raise
        finally:
            if self.dry_run:
                self.logger.info(
                    f"DRY RUN COMPLETE - "
                    f"Total: {total_files_processed}, "
                    f"Successful: {total_files_successful}, "
                    f"Failed: {total_files_failed}, "
                    f"MP4 files that would be moved to upload: {mp4_files_moved}, "
                    f"Non-MP4 files that would be moved to transcode: {non_mp4_files_moved}"
                )
            else:
                self.logger.info(
                    f"Media renaming completed - "
                    f"Total: {total_files_processed}, "
                    f"Successful: {total_files_successful}, "
                    f"Failed: {total_files_failed}, "
                    f"MP4 files moved to upload: {mp4_files_moved}, "
                    f"Non-MP4 files moved to transcode: {non_mp4_files_moved}"
                )

    def _setup_directories(self) -> None:
        """Ensure all required directories exist."""
        directories = [
            Path(MEDIA_BASE_FOLDER, TRANSCODE_FOLDER) / CONTENT_TYPE_MOVIES,
            Path(MEDIA_BASE_FOLDER, TRANSCODE_FOLDER) / CONTENT_TYPE_TV,
            Path(MEDIA_BASE_FOLDER, UPLOAD_FOLDER) / CONTENT_TYPE_MOVIES,
            Path(MEDIA_BASE_FOLDER, UPLOAD_FOLDER) / CONTENT_TYPE_TV,
            Path(MEDIA_BASE_FOLDER, ERROR_FOLDER),
        ]

        for directory in directories:
            ensure_directory_exists(directory)
            self.logger.debug(f"Ensured directory exists: {directory}")

    def _process_file(self, filepath: Path, content_type: str) -> bool:
        """Process a single media file through the renaming pipeline."""
        self.logger.info(f"Processing file: {filepath}")

        try:
            # Step 1: Parse filename
            media_info = parse_media_file(filepath)
            self.logger.debug(f"Parsed media info: {media_info}")

            # Step 2: Lookup TMDb metadata
            tmdb_data = self._lookup_tmdb_metadata(media_info)
            if not tmdb_data:
                return self._handle_error(filepath, "TMDb lookup failed")

            # Step 2.5: For TV shows, fetch the actual episode title from TMDb
            if content_type == CONTENT_TYPE_TV:
                self._fetch_episode_title_from_tmdb(media_info, tmdb_data)

            # Step 3: Format new filename and path
            new_path = self._format_new_path(media_info, tmdb_data, filepath)
            self.logger.debug(f"New path: {new_path}")

            # Step 4: Move to appropriate destination based on file extension
            return self._move_to_destination(filepath, new_path, content_type)

        except Exception as e:
            self.logger.error(f"Processing failed for {filepath}: {e}")
            return self._handle_error(filepath, str(e))

    def _lookup_tmdb_metadata(self, media_info: dict) -> dict | None:
        """Lookup metadata from TMDb API."""
        try:
            if media_info["content_type"] == CONTENT_TYPE_MOVIES:
                result = self.tmdb_client.find_best_movie_match(media_info["title"], media_info["year"])
            else:  # TV Show
                result = self.tmdb_client.find_best_tv_match(media_info["title"], media_info["year"],
                                                             self.use_episode_titles)

            if result:
                # Use appropriate field name for movies vs TV shows
                display_name = result.get("title") or result.get("name", "Unknown")
                self.logger.debug(f"Found TMDb match: {display_name}")
                return result
            else:
                self.logger.warning(f"No TMDb match found for: {media_info['title']}")
                return None

        except TMDbError as e:
            self.logger.error(f"TMDb lookup failed: {e}")
            return None

    def _fetch_episode_title_from_tmdb(self, media_info: dict, tmdb_data: dict) -> None:
        """Fetch the actual episode title from TMDb and update media_info.

        Also updates season and episode numbers if they were corrected during the search.
        """
        try:
            season = media_info.get("season")
            episode = media_info.get("episode")
            tmdb_id = tmdb_data.get("id")

            if not all([season, episode, tmdb_id]):
                self.logger.debug("Missing season/episode/tmdb_id, skipping TMDb episode title fetch")
                return

            # Fetch the episode details from TMDb
            episode_data = self.tmdb_client.get_episode_info(
                tmdb_id,
                season,
                episode,
                episode_title=media_info.get("episode_title"),
                use_episode_title=self.use_episode_titles
            )

            if episode_data and "name" in episode_data:
                original_title = media_info.get("episode_title", "")
                new_title = episode_data["name"]
                media_info["episode_title"] = new_title
                self.logger.info(f"Updated episode title from TMDb: '{original_title}' -> '{new_title}'")

                # Update season and episode numbers if they were corrected during the search
                if "season_number" in episode_data:
                    original_season = media_info.get("season")
                    new_season = episode_data["season_number"]
                    if new_season != original_season:
                        media_info["season"] = new_season
                        self.logger.info(f"Updated season from TMDb: {original_season} -> {new_season}")

                if "episode_number" in episode_data:
                    original_episode = media_info.get("episode")
                    new_episode = episode_data["episode_number"]
                    if new_episode != original_episode:
                        media_info["episode"] = new_episode
                        self.logger.info(f"Updated episode from TMDb: {original_episode} -> {new_episode}")
            else:
                self.logger.debug(f"Could not fetch episode title for S{season}E{episode} from TMDb")

        except Exception as e:
            self.logger.debug(f"Failed to fetch episode title from TMDb: {e}")
            # Don't fail the entire operation if we can't fetch the episode title

    @staticmethod
    def _format_new_path(media_info: dict, tmdb_data: dict, filepath: Path) -> Path:
        """Format the new path according to Plex conventions."""
        tmdb_id = tmdb_data["id"]
        extension = filepath.suffix

        if media_info["content_type"] == CONTENT_TYPE_MOVIES:
            # Destination will be determined by file extension
            new_path = construct_movie_path(
                tmdb_data["title"],
                int(tmdb_data["release_date"][:4]) if tmdb_data.get("release_date") else media_info["year"],
                tmdb_id,
                extension,
            )
        else:  # TV Show
            # Destination will be determined by file extension
            new_path = construct_tv_show_path(
                tmdb_data["name"],
                int(tmdb_data["first_air_date"][:4]) if tmdb_data.get("first_air_date") else media_info["year"],
                tmdb_id,
                media_info["season"],
                media_info["episode"],
                media_info["episode_title"],
                extension
            )

        return new_path

    def _move_to_destination(self, source_path: Path, new_path: Path, content_type: str) -> bool:
        """Move file to appropriate destination based on file extension."""
        extension = source_path.suffix.lower()
        is_mp4 = extension == ".mp4"

        if is_mp4:
            # MP4 files go directly to upload folder
            destination_dir = Path(MEDIA_BASE_FOLDER, UPLOAD_FOLDER)
            self.logger.info(f"MP4 file detected, moving to upload folder: {destination_dir}")
        else:
            # Non-MP4 files go to transcode folder
            destination_dir = Path(MEDIA_BASE_FOLDER, TRANSCODE_FOLDER)
            self.logger.info(f"Non-MP4 file detected, moving to transcode folder: {destination_dir}")

        # Extract the relative path from new_path (remove the MEDIA_BASE_FOLDER prefix)
        # new_path is like: ../media/Movies/Title (Year) {tmdb-id}/Title (Year) {tmdb-id}.ext
        # We want: Movies/Title (Year) {tmdb-id}/Title (Year) {tmdb-id}.ext
        new_path_str = str(new_path)
        # Remove the leading ../media/ from the path
        if new_path_str.startswith("../media/"):
            relative_path = Path(new_path_str[9:])  # Skip "../media/"
        elif new_path_str.startswith("../"):
            relative_path = Path(new_path_str[3:])  # Skip "../"
        else:
            relative_path = new_path

        # Construct the full destination path: transcode/Movies/Title/file.ext
        destination_path = destination_dir / relative_path

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would move {source_path} to {destination_path}")
            return True  # Dry run always "succeeds"

        error_dir = create_error_directory(Path(MEDIA_BASE_FOLDER, ERROR_FOLDER), "renaming_errors")
        success = safe_move_with_backup(source_path, destination_path, error_dir)

        if success:
            # Extract just the filename for logging
            destination_relative = destination_path.relative_to(destination_dir)
            self.logger.info(f"Successfully moved: {source_path.name} -> {destination_relative}")
        else:
            self.logger.error(f"Failed to move: {source_path.name}")

        return success  # Return actual success status

    def _handle_error(self, filepath: Path, error_message: str) -> bool:
        """Handle processing errors by moving file to error directory."""
        self.logger.error(f"Handling error for {filepath}: {error_message}")

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would move {filepath} to error directory")
            return False

        error_dir = create_error_directory(Path(MEDIA_BASE_FOLDER, ERROR_FOLDER), "processing_errors")
        error_destination = error_dir / filepath.name

        try:
            safe_move_with_backup(filepath, error_destination)
            return False
        except Exception as e:
            self.logger.error(f"Failed to move error file: {e}")
            return False


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Plex media file renamer - handles parsing, TMDb lookup, and file organization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
 Examples:
   %(prog)s                                    # Process from default queue directory
   %(prog)s /path/to/media                    # Process from custom directory
   %(prog)s --dry-run                         # Preview changes without modifications
   %(prog)s --log-level DEBUG                 # Enable debug logging
   %(prog)s --use-episode-titles              # Use episode titles instead of S##E## numbers for TV shows
        """,
    )

    parser.add_argument(
        "source_dir",
        nargs="?",
        help="Source directory containing media files (default: ../ready-to-process)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without making modifications",
    )

    parser.add_argument(
        "--use-episode-titles",
        action="store_true",
        help="Use episode titles instead of S##E## numbers for TV shows (useful when episode numbers are incorrect)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        default=DEFAULT_LOG_LEVEL,
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Create and run the media renamer
    renamer = MediaRenamer(
        dry_run=args.dry_run,
        log_level=args.log_level,
        use_episode_titles=getattr(args, "use_episode_titles", False),
    )

    try:
        renamer.run(args.source_dir)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
