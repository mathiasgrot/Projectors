"""
Cleaning up after projectors that were deleted outside the addon (X / Delete
in the viewport, Delete in the Outliner).

Blender only deletes what is selected. A projector's spot light and body are
unselectable children, so deleting the camera leaves them behind, unparented.
Its EEVEE node group would also stay in the receiving materials and keep
projecting. This module removes all of that:

* spot lights and bodies of the addon that lost their projector camera,
* EEVEE node groups that no projector uses any more (removed from the
  materials, together with their shadow map).
"""

import bpy

from .helper import ADDON_ID
from . import body, eevee

SPOT_KEY = ADDON_ID.format('spot')

_scheduled = False


def _orphans():
    objs = [o for o in bpy.data.objects
            if o.parent is None and (o.get(SPOT_KEY) or o.get(body.BODY_KEY))]
    used = {o.proj_settings.eevee_node_group for o in bpy.data.objects
            if o.type == 'CAMERA' and o.proj_settings.eevee_node_group is not None}
    groups = [g for g in bpy.data.node_groups
              if g.get(eevee.GROUP_VERSION_KEY) is not None and g not in used]
    return objs, groups


def check(depsgraph=None):
    """ Called from the depsgraph handler; cheap when there's nothing to do. """
    global _scheduled
    if _scheduled:
        return
    objs, groups = _orphans()
    if objs or groups:
        _scheduled = True
        # Deferred: don't delete data while Blender is still in the middle of
        # the delete operation that triggered the update.
        bpy.app.timers.register(_clean, first_interval=0.0)


def _remove_group(group):
    for mat in bpy.data.materials:
        eevee.remove_from_material(mat, group)
    tex = group.nodes.get('shadow_tex')
    img = tex.image if tex else None
    bpy.data.node_groups.remove(group)
    if img is not None and img.name.startswith('_proj.shadow') and img.users == 0:
        bpy.data.images.remove(img)


def _remove_object(obj):
    data = obj.data
    trees = set()
    if isinstance(data, bpy.types.Light) and data.node_tree:
        # The light's own node groups ('_Projector', pixel grid) go with it.
        trees = {n.node_tree for n in data.node_tree.nodes
                 if n.type == 'GROUP' and n.node_tree is not None}
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if isinstance(data, bpy.types.Light):
            bpy.data.lights.remove(data)
        elif isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
    for tree in trees:
        if tree.users == 0:
            bpy.data.node_groups.remove(tree)


def _clean():
    global _scheduled
    _scheduled = False
    from . import registry
    registry.invalidate()
    objs, groups = _orphans()
    for g in groups:
        try:
            _remove_group(g)
        except Exception as e:
            print(f'[Projectors Addon]: cleanup of {g.name} failed: {e}')
    for o in objs:
        try:
            _remove_object(o)
        except Exception as e:
            print(f'[Projectors Addon]: cleanup of {o.name} failed: {e}')
    return None


def unregister():
    if bpy.app.timers.is_registered(_clean):
        bpy.app.timers.unregister(_clean)
