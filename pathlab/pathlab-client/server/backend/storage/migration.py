import asyncio
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database.models import WSISlide, TrainedModel, AIResult
from backend.auth.models import User

logger = logging.getLogger(__name__)


class MigrationManager:
    def __init__(self):
        self._migration_process: Optional[subprocess.Popen[Any]] = None
        self._source: Optional[str] = None
        self._destination: Optional[str] = None
        self._status: str = "idle"  # idle, running, completed, failed
        self._error: Optional[str] = None
        self._total_progress: float = 0.0
        self._delete_source: bool = False
        self._conflicts: list[str] = []
        self._copy_succeeded: bool = False
        self._validation_failed: bool = False
        self._finalization_safe: bool = False

    async def start_migration(
        self, source: str, destination: str, delete_source: bool = False
    ) -> bool:
        """
        Start a migration process using rsync.

        Args:
            source: Source directory path
            destination: Destination directory path
            delete_source: Whether to delete the source after successful migration

        Returns:
            bool: True if started successfully, False if already running
        """
        if self._status == "running":
            return False

        self._source = source
        self._destination = destination
        self._delete_source = delete_source
        self._status = "running"
        self._error = None
        self._total_progress = 0.0
        self._conflicts = []
        self._copy_succeeded = False
        self._validation_failed = False
        self._finalization_safe = False

        try:
            # Ensure destination parent exists
            Path(destination).mkdir(parents=True, exist_ok=True)

            # Construct rsync command
            # -a: archive mode
            # -v: verbose
            # --info=progress2: show total progress
            # --no-inc-recursive: scan whole tree first for better progress
            cmd = [
                "rsync",
                "-a",
                "--info=progress2",
                "--no-inc-recursive",
                "--ignore-existing",
                f"{source}/",
                destination,
            ]

            self._conflicts = self._collect_conflicts(source, destination)

            logger.info(f"Starting migration: {' '.join(cmd)}")

            # Start process asynchronously
            self._migration_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
            )

            # Start monitoring in background
            asyncio.create_task(self._monitor_migration())
            return True

        except Exception as e:
            logger.error(f"Failed to start migration: {e}")
            self._status = "failed"
            self._error = str(e)
            return False

    async def _monitor_migration(self):
        """Monitor the running rsync process and update progress."""
        if not self._migration_process:
            return

        try:
            # Read rsync output line by line
            # Rsync with --info=progress2 outputs lines with \r, so we need to handle that
            while True:
                line = await asyncio.to_thread(self._migration_process.stdout.readline)
                if not line and self._migration_process.poll() is not None:
                    break

                if line:
                    # Example info=progress2 output:
                    # 1,234,567   10%  123.45MB/s    0:00:01 (xfr#1, to-chk=0/100)
                    parts = line.split()
                    for part in parts:
                        if "%" in part:
                            try:
                                percentage = float(part.replace("%", ""))
                                self._total_progress = percentage
                            except ValueError:
                                pass

                # Small sleep to yield
                await asyncio.sleep(0.1)

            # Check final return code
            return_code = self._migration_process.wait()

            if return_code == 0:
                self._status = "completed"
                self._total_progress = 100.0
                self._copy_succeeded = True
                self._finalization_safe = not self._validation_failed
                logger.info("Migration completed successfully")
            else:
                _, stderr = self._migration_process.communicate()
                self._status = "failed"
                self._error = f"Rsync failed with code {return_code}: {stderr}"
                self._copy_succeeded = False
                self._finalization_safe = False
                logger.error(self._error)

        except Exception as e:
            logger.error(f"Error monitoring migration: {e}")
            self._status = "failed"
            self._error = str(e)
            self._copy_succeeded = False
            self._finalization_safe = False
        finally:
            self._migration_process = None

    def _collect_conflicts(self, source: str, destination: str) -> list[str]:
        source_root = Path(source)
        destination_root = Path(destination)
        conflicts: list[str] = []

        if not source_root.exists() or not destination_root.exists():
            return conflicts

        for src in source_root.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(source_root)
            if (destination_root / rel).exists():
                conflicts.append(str(rel))

        return conflicts

    async def update_database_paths(
        self, db: AsyncSession, old_path_str: str, new_path_str: str
    ):
        """
        Update paths in the database to point to the new location.
        """
        logger.info(f"Updating database paths from {old_path_str} to {new_path_str}")

        old_root = Path(old_path_str)
        new_root = Path(new_path_str)

        def rewrite_descendant_path(value: object) -> tuple[object, bool]:
            if not isinstance(value, str):
                return value, False

            src = Path(value)
            if not src.is_absolute():
                return value, False

            try:
                rel = src.relative_to(old_root)
            except ValueError:
                return value, False

            return str(new_root / rel), True

        def rewrite_json_paths(value: object) -> tuple[object, bool]:
            if isinstance(value, dict):
                changed = False
                rewritten: dict[str, object] = {}
                for key, item in value.items():
                    new_item, item_changed = rewrite_json_paths(item)
                    rewritten[key] = new_item
                    changed = changed or item_changed
                return rewritten, changed

            if isinstance(value, list):
                changed = False
                rewritten: list[object] = []
                for item in value:
                    new_item, item_changed = rewrite_json_paths(item)
                    rewritten.append(new_item)
                    changed = changed or item_changed
                return rewritten, changed

            return rewrite_descendant_path(value)

        try:
            # 1. Update WSI Slides
            stmt = select(WSISlide)
            result = await db.execute(stmt)
            wsis = result.scalars().all()

            count = 0
            for wsi in wsis:
                wsi_path, wsi_changed = rewrite_descendant_path(wsi.wsi_path)
                associated_files, associated_changed = rewrite_json_paths(
                    wsi.associated_files
                )

                if wsi_changed:
                    wsi.wsi_path = wsi_path

                if associated_changed:
                    wsi.associated_files = associated_files

                if wsi_changed or associated_changed:
                    count += 1

            logger.info(f"Updated {count} WSI paths")

            # 2. Update Trained Models
            stmt = select(TrainedModel)
            result = await db.execute(stmt)
            models = result.scalars().all()

            count = 0
            for model in models:
                updated = False
                model_path, model_path_changed = rewrite_descendant_path(
                    model.model_path
                )
                if model_path_changed:
                    model.model_path = model_path
                    updated = True

                config_path, config_path_changed = rewrite_descendant_path(
                    model.config_path
                )
                if config_path_changed:
                    model.config_path = config_path
                    updated = True

                if updated:
                    count += 1

            logger.info(f"Updated {count} Trained Model paths")

            # 3. Update AI Results (Feature paths / Attention paths in metadata)
            # This is trickier because it's JSON
            stmt = select(AIResult)
            result = await db.execute(stmt)
            results = result.scalars().all()

            count = 0
            for res in results:
                if isinstance(res.extra_metadata, dict):
                    # Check for attention_path
                    meta = cast(dict[str, object], dict(res.extra_metadata))
                    changed = False

                    attention_path = meta.get("attention_path")
                    if attention_path:
                        rewritten_attention_path, attention_changed = (
                            rewrite_descendant_path(attention_path)
                        )
                        if attention_changed:
                            meta["attention_path"] = rewritten_attention_path
                            changed = True

                    if changed:
                        res.extra_metadata = meta
                        count += 1

            logger.info(f"Updated {count} AI Result metadata paths")

            stmt = select(User)
            result = await db.execute(stmt)
            users = result.scalars().all()

            count = 0
            for user in users:
                avatar_path, avatar_changed = rewrite_descendant_path(user.avatar_path)
                if avatar_changed:
                    user.avatar_path = avatar_path
                    count += 1

            logger.info(f"Updated {count} User avatar paths")

            await db.commit()

        except Exception as e:
            logger.error(f"Failed to update database paths: {e}")
            await db.rollback()
            raise

    def cleanup_source(self):
        """
        Delete the source directory if delete_source was requested.
        SAFETY: Only delete if status is completed and source is set.
        """
        if self._status != "completed" or not self._delete_source or not self._source:
            return

        if (
            not self._copy_succeeded
            or self._validation_failed
            or not self._finalization_safe
            or bool(self._conflicts)
        ):
            return

        logger.warning(f"Cleaning up source directory: {self._source}")
        try:
            shutil.rmtree(self._source)
            logger.info("Source directory cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup source directory: {e}")
            # Don't fail the whole operation, just log error

    def get_status(self) -> Dict[str, Any]:
        """Get current migration status."""
        return {
            "status": self._status,
            "source": self._source,
            "destination": self._destination,
            "progress": self._total_progress,
            "error": self._error,
            "delete_source": self._delete_source,
            "conflicts": self._conflicts,
            "copy_succeeded": self._copy_succeeded,
            "validation_failed": self._validation_failed,
            "finalization_safe": self._finalization_safe,
        }

    def reset(self):
        """Reset status to idle."""
        if self._status != "running":
            self._status = "idle"
            self._error = None
            self._total_progress = 0.0
            self._source = None
            self._destination = None
            self._delete_source = False
            self._conflicts = []
            self._copy_succeeded = False
            self._validation_failed = False
            self._finalization_safe = False


# Global instance
migration_manager = MigrationManager()
