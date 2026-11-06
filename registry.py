"""
Cached lists of the addon's projectors and bodies.

The depsgraph handler runs on every scene update, including every frame while
dragging an object. Scanning all of bpy.data.objects each time gets noticeable
in big scenes, so the lists are only rebuilt when objects or node groups are
added or removed (or something was renamed or deleted in between, which the
liveness check catches).
"""

import bpy

_key = None
_projectors = []
_bodies = []

BODY_KEY = 'projectors_body'


def invalidate():
    global _key
    _key = None


def _alive(obj):
    try:
        obj.name
        return True
    except ReferenceError:
        return False


def _structure_key():
    return (len(bpy.data.objects), len(bpy.data.node_groups))


def refresh():
    """ Rebuild the lists if needed. Returns True if they were rebuilt. """
    global _key, _projectors, _bodies
    key = _structure_key()
    if key == _key and all(_alive(o) for o in _projectors) and all(_alive(o) for o in _bodies):
        return False
    _projectors = [o for o in bpy.data.objects
                   if o.type == 'CAMERA' and o.name.startswith('Projector')]
    _bodies = [o for o in bpy.data.objects if o.type == 'MESH' and o.get(BODY_KEY)]
    _key = key
    return True


def projectors():
    refresh()
    return [o for o in _projectors if _alive(o)]


def bodies():
    refresh()
    return [o for o in _bodies if _alive(o)]
