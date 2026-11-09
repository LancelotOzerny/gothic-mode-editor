"""Process-local preview scene: transfer textures once, then only camera parameters."""
from .preview_render import render_mesh

_scene = None


def render_frame(scene, parameters):
    global _scene
    if scene is not None:_scene = scene
    if _scene is None:raise ValueError('Preview scene is not loaded')
    mesh, textures = _scene
    width, height, *camera = parameters
    pixels = render_mesh(mesh,textures,width,height,*camera)
    return f'P6\n{width} {height}\n255\n'.encode('ascii') + pixels
