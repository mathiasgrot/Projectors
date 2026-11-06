"""
Baked shadow maps for EEVEE projectors.

This is classic shadow mapping, done offline: for every texel of the projected
image, a ray is cast from the projector into the scene and the distance to the
first hit is stored in a float image. The EEVEE node group samples that image
with the same coordinates as the projected content and only lights a point if
it isn't farther away than the stored distance (plus a small bias).

The map has to be re-baked when the set or the projector changes. With "Auto
Update" on, that happens shortly after objects stop moving in the viewport.
"""

import time

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Vector
from mathutils.bvhtree import BVHTree

FAR = 1.0e6
CASTER_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT'}
AUTO_DELAY = 0.4  # seconds without changes before an automatic re-bake


def _projectors_with_shadows():
    from . import registry
    return [o for o in registry.projectors()
            if o.proj_settings.eevee_node_group is not None
            and o.proj_settings.eevee_shadows]


def _get_spot(projector):
    for child in projector.children:
        if child.type == 'LIGHT':
            return child
    return None


def build_scene_bvh(depsgraph, exclude=()):
    """ One BVH tree with every visible shadow casting surface, in world space. """
    verts_all = []
    tris_all = []
    offset = 0
    for inst in depsgraph.object_instances:
        obj = inst.object
        if obj.type not in CASTER_TYPES:
            continue
        orig = obj.original
        if orig in exclude or orig.hide_render:
            continue
        if not getattr(orig, 'visible_shadow', True):
            continue
        try:
            mesh = obj.to_mesh()
        except RuntimeError:
            continue
        if mesh is None:
            continue
        try:
            mesh.calc_loop_triangles()
            nv = len(mesh.vertices)
            nt = len(mesh.loop_triangles)
            if nv == 0 or nt == 0:
                continue
            co = np.empty(nv * 3, np.float32)
            mesh.vertices.foreach_get('co', co)
            co = co.reshape(-1, 3)
            tris = np.empty(nt * 3, np.int32)
            mesh.loop_triangles.foreach_get('vertices', tris)
            mw = np.array(inst.matrix_world, np.float32)
            co = co @ mw[:3, :3].T + mw[:3, 3]
            verts_all.append(co)
            tris_all.append(tris.reshape(-1, 3) + offset)
            offset += nv
        finally:
            obj.to_mesh_clear()
    if not verts_all:
        return None
    verts = np.concatenate(verts_all).tolist()
    tris = np.concatenate(tris_all).tolist()
    return BVHTree.FromPolygons(verts, tris, all_triangles=True)


def bake_size(projector):
    """ Width and height of the shadow map, following the projector's aspect ratio. """
    from .projector import get_resolution_for
    settings = projector.proj_settings
    w, h = get_resolution_for(projector)
    longest = int(settings.shadow_resolution)
    if w >= h:
        return longest, max(1, round(longest * h / w))
    return max(1, round(longest * w / h)), longest


def bake(projector, depsgraph=None, bvh=None):
    """ Bake the shadow map of one projector. Returns the time it took. """
    t0 = time.perf_counter()
    settings = projector.proj_settings
    group = settings.eevee_node_group
    spot = _get_spot(projector)
    if group is None or spot is None:
        return 0.0
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    if bvh is None:
        bvh = build_scene_bvh(depsgraph, exclude={projector, spot})

    w, h = bake_size(projector)

    # Invert the projection mapping of the node group: texel centre -> ray in
    # the spot's local space (the spot looks down -Z).
    pm = group.nodes['proj_map']
    loc = pm.inputs[1].default_value
    scale = pm.inputs[3].default_value
    u = (np.arange(w, dtype=np.float64) + 0.5) / w
    v = (np.arange(h, dtype=np.float64) + 0.5) / h
    uu, vv = np.meshgrid(u, v)  # rows go bottom to top, like image pixels
    x = (uu - 0.5) * scale[0] + loc[0]
    y = (vv - 0.5) * scale[1] + loc[1]
    local = np.stack([x, y, -np.ones_like(x)], axis=-1).reshape(-1, 3)

    mw = spot.matrix_world
    rot = np.array(mw.to_3x3().normalized(), np.float64)
    dirs = local @ rot.T
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    origin = Vector(mw.translation)

    depth = np.full(w * h, FAR, np.float32)
    if bvh is not None:
        cast = bvh.ray_cast
        for i, d in enumerate(dirs.tolist()):
            hit = cast(origin, d)
            if hit[3] is not None:
                depth[i] = hit[3]

    img = _ensure_image(projector, w, h)
    px = np.empty((w * h, 4), np.float32)
    px[:, 0] = px[:, 1] = px[:, 2] = depth
    px[:, 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.update()
    settings.shadow_bake_time = time.perf_counter() - t0
    from . import eevee
    eevee.sync(projector)
    return settings.shadow_bake_time


def _ensure_image(projector, w, h):
    settings = projector.proj_settings
    img = settings.shadow_image
    if img is not None and tuple(img.size) != (w, h):
        settings.shadow_image = None
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(f'_proj.shadow.{projector.name}', w, h,
                                  alpha=False, float_buffer=True)
        img.colorspace_settings.name = 'Non-Color'
        settings.shadow_image = img
    return img


def bake_all(projectors, depsgraph=None):
    if not projectors:
        return
    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    exclude = set()
    for p in projectors:
        exclude.add(p)
        spot = _get_spot(p)
        if spot:
            exclude.add(spot)
    # Projectors don't cast shadows, so one tree serves all of them.
    bvh = build_scene_bvh(depsgraph, exclude=exclude)
    for p in projectors:
        bake(p, depsgraph, bvh)


# ---------------------------------------------------------------------------
# Automatic re-bake, debounced
# ---------------------------------------------------------------------------

_last_change = 0.0
_timer_running = False
_baking = False


def on_depsgraph_update(depsgraph):
    """ Called from the addon's depsgraph handler. Starts a re-bake timer when
    something moved or its geometry changed. """
    global _last_change, _timer_running
    if _baking:
        return
    if not any(p.proj_settings.shadow_auto_update for p in _projectors_with_shadows()):
        return
    changed = False
    for upd in depsgraph.updates:
        if isinstance(upd.id, bpy.types.Object) and (upd.is_updated_transform or upd.is_updated_geometry):
            changed = True
            break
    if not changed:
        return
    _last_change = time.monotonic()
    if not _timer_running:
        _timer_running = True
        bpy.app.timers.register(_auto_bake, first_interval=AUTO_DELAY)


def _auto_bake():
    global _timer_running, _baking
    wait = AUTO_DELAY - (time.monotonic() - _last_change)
    if wait > 0:
        return wait
    _timer_running = False
    projectors = [p for p in _projectors_with_shadows() if p.proj_settings.shadow_auto_update]
    if not projectors:
        return None
    _baking = True
    try:
        view_layer = getattr(bpy.context, 'view_layer', None)
        if view_layer is None:
            view_layer = projectors[0].users_scene[0].view_layers[0]
        bake_all(projectors, view_layer.depsgraph)
    except Exception as e:  # never let a timer error spam the console
        print(f'[Projectors Addon]: shadow bake failed: {e}')
    finally:
        _baking = False
    return None


@persistent
def _pack_on_save(*args):
    """ Baked maps only live in memory; pack them so they're saved in the .blend. """
    for p in bpy.data.objects:
        if p.type != 'CAMERA' or not p.name.startswith('Projector'):
            continue
        img = p.proj_settings.shadow_image
        if img is not None and (img.is_dirty or not img.packed_file):
            img.pack()


def register():
    if _pack_on_save not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_pack_on_save)


def unregister():
    if _pack_on_save in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_pack_on_save)
    if bpy.app.timers.is_registered(_auto_bake):
        bpy.app.timers.unregister(_auto_bake)
