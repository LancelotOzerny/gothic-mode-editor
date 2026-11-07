"""Publish files across directories/volumes, restoring all prior files on error."""
from pathlib import Path
import shutil
from uuid import uuid4


def publish_files(pairs, commit=lambda: None):
    prepared, published = [], []
    try:
        for source, destination in pairs:
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            token = uuid4().hex
            temporary = destination.with_name('.' + destination.name + '.' + token + '.tmp')
            backup = destination.with_name('.' + destination.name + '.' + token + '.bak')
            prepared.append((destination, temporary, backup))
            if source is not None:shutil.copy2(source, temporary)
            if destination.exists():shutil.copy2(destination, backup)
        for destination, temporary, backup in prepared:
            if temporary.exists():temporary.replace(destination)
            else:destination.unlink(missing_ok=True)
            published.append((destination, backup))
        commit()
    except Exception:
        for destination, backup in reversed(published):
            if backup.exists():backup.replace(destination)
            else:destination.unlink(missing_ok=True)
        raise
    finally:
        for _, temporary, backup in prepared:
            temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
