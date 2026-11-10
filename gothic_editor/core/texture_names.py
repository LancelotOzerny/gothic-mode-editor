"""Shared basename lookup for texture references in models."""
from pathlib import Path


def texture_candidates(name):
    name = name.replace('\\', '/').rsplit('/', 1)[-1].lower()
    stem = Path(name).stem
    candidates = [name]
    if not stem.endswith('-c'):
        candidates.append(stem + '-c.tex')
    candidates.extend((stem + '.tex', stem + '.tga'))
    return list(dict.fromkeys(candidates))


def material_texture_name(filename):
    """A compiled NAME-C.TEX corresponds to the logical material name NAME.TGA."""
    path = Path(filename)
    if path.suffix.lower() == '.tex' and path.stem.lower().endswith('-c'):
        return path.stem[:-2] + '.TGA'
    return path.name
