"""
Duplicating projectors.

A projector is a camera with a hidden, unselectable spot light child that does
the actual projection. Blender's own Shift+D (and copy/paste) only copies what
is selected, so the copy used to be a bare camera without its spot, and it
would have shared node groups with the original anyway.

This module repairs such copies: when a projector camera without a spot shows
up, it gets its own spot, node trees, body and EEVEE setup, with the settings,
custom image and EEVEE receivers of the projector it was copied from. The
Duplicate button in the panel goes through the same code.
"""

import uuid

import bpy
from mathutils import Matrix

from .helper import get_spot
from . import body, eevee, shadows


def _is_projector_camera(obj):
    return obj.type == 'CAMERA' and obj.name.startswith('Projector')


def ensure_uid(projector):
    ps = projector.proj_settings
    if not ps.projector_uid:
        ps.projector_uid = uuid.uuid4().hex
    return ps.projector_uid


def find_source(copy):
    uid = copy.proj_settings.projector_uid
    if not uid:
        return None
    for obj in bpy.data.objects:
        if obj is not copy and _is_projector_camera(obj) and get_spot(obj) is not None \
                and obj.proj_settings.projector_uid == uid:
            return obj
    return None


def make_independent(copy, source=None):
    """ Turn a bare copy of a projector camera into a full projector. """
    from .projector import create_spot, apply_settings
    ps = copy.proj_settings
    src_group = source.proj_settings.eevee_node_group if source else None

    # Pointers copied from the source must not be shared.
    ps.eevee_node_group = None
    ps.shadow_image = None
    ps.projector_uid = uuid.uuid4().hex

    spot = get_spot(copy) or create_spot(copy)

    if source is not None:
        src_spot = get_spot(source)
        if src_spot and src_spot.data.node_tree:
            src_node = src_spot.data.node_tree.nodes.get('Image Texture')
            dst_node = spot.data.node_tree.nodes.get('Image Texture')
            if src_node and dst_node:
                dst_node.image = src_node.image
                dst_node.interpolation = src_node.interpolation
                for attr in ('frame_duration', 'frame_start', 'frame_offset',
                             'use_cyclic', 'use_auto_refresh'):
                    setattr(dst_node.image_user, attr, getattr(src_node.image_user, attr))
        if src_spot:
            spot.data.color = src_spot.data.color

    apply_settings(copy)

    if ps.show_body and body.get_body(copy) is None:
        body.create_body(copy)

    # Project onto the same materials as the source.
    if src_group is not None:
        mats = [m for m in bpy.data.materials if eevee.material_has_projector(m, src_group)]
        if mats:
            group = eevee.ensure_eevee_node_group(copy)
            ps.receivers.clear()
            for m in mats:
                eevee.add_to_material(m, group)
                eevee.record_receiver(copy, m)
            if ps.eevee_shadows:
                try:
                    shadows.bake(copy, _depsgraph(copy))
                except Exception as e:
                    print(f'[Projectors Addon]: shadow bake of {copy.name} failed: {e}')
    return copy


def _depsgraph(obj):
    view_layer = getattr(bpy.context, 'view_layer', None)
    if view_layer is None:
        view_layer = obj.users_scene[0].view_layers[0]
    view_layer.update()
    return view_layer.depsgraph


def duplicate(projector, offset=None):
    """ Duplicate a projector next to the original. Returns the new projector. """
    new = projector.copy()
    if projector.data is not None:
        new.data = projector.data.copy()
    for coll in projector.users_collection:
        coll.objects.link(new)
    if offset is None:
        ps = projector.proj_settings
        offset = (ps.body_size[0] + 0.1) if ps.show_body else 0.5
    new.matrix_world = projector.matrix_world @ Matrix.Translation((offset, 0.0, 0.0))
    make_independent(new, projector)
    return new


# ---------------------------------------------------------------------------
# Repairing Shift+D / copy-paste copies
# ---------------------------------------------------------------------------

_repair_scheduled = False


def check(depsgraph=None):
    """ Called from the depsgraph handler. Cheap: only looks at projector cameras. """
    global _repair_scheduled
    needs_repair = False
    for obj in bpy.data.objects:
        if not _is_projector_camera(obj):
            continue
        spot = get_spot(obj)
        if spot is None:
            needs_repair = True
            continue
        if not obj.proj_settings.projector_uid:
            # Give existing projectors an id now, so a later copy can find its source.
            ensure_uid(obj)
        tree = spot.data.node_tree
        node = tree.nodes.get('Image Texture') if tree else None
        if node is not None and node.image is not None and obj.proj_settings.custom_image != node.image:
            obj.proj_settings.custom_image = node.image   # backup for Reinit
    if needs_repair and not _repair_scheduled:
        _repair_scheduled = True
        # Deferred: Shift+D is still running its grab when the handler fires.
        bpy.app.timers.register(_repair, first_interval=0.0)


def _repair():
    global _repair_scheduled
    _repair_scheduled = False
    copies = [o for o in bpy.data.objects if _is_projector_camera(o) and get_spot(o) is None]
    # Find all sources first: repairing gives copies new ids.
    pairs = [(c, find_source(c)) for c in copies]
    for copy, source in pairs:
        try:
            make_independent(copy, source)
        except Exception as e:
            print(f'[Projectors Addon]: could not set up copied projector {copy.name}: {e}')
    return None


def unregister():
    if bpy.app.timers.is_registered(_repair):
        bpy.app.timers.unregister(_repair)


# ---------------------------------------------------------------------------
# Reinit: rebuild a projector from its settings
# ---------------------------------------------------------------------------

def reinit(projector):
    """ Rebuild the spot light, node trees, body and EEVEE setup of a projector
    from its settings. Keeps the custom image and the EEVEE receivers. """
    from .projector import create_spot, apply_settings
    from . import cleanup
    ps = projector.proj_settings

    # Remember what to restore.
    image_info = None
    old_spots = [c for c in projector.children
                 if c.type == 'LIGHT' or c.get(cleanup.SPOT_KEY)]
    for spot in old_spots:
        tree = getattr(spot.data, 'node_tree', None)
        node = tree.nodes.get('Image Texture') if tree else None
        if node is not None:
            image_info = (node.image, node.interpolation,
                          {a: getattr(node.image_user, a) for a in
                           ('frame_duration', 'frame_start', 'frame_offset',
                            'use_cyclic', 'use_auto_refresh')})
            break
    color = old_spots[0].data.color[:] if old_spots and old_spots[0].type == 'LIGHT' else None

    group = ps.eevee_node_group
    if image_info is None or image_info[0] is None:
        # The light's tree is gone: fall back to the EEVEE copy, then the backup.
        fallback = None
        if group is not None and group.nodes.get('custom_img') is not None:
            fallback = group.nodes['custom_img'].image
        fallback = fallback or ps.custom_image
        if fallback is not None:
            image_info = (fallback, 'Linear', {})

    mats = [m for m in bpy.data.materials if group and eevee.material_has_projector(m, group)]
    for m in eevee.recorded_receivers(projector):
        if m not in mats:
            mats.append(m)

    # Tear down.
    if group is not None:
        for m in bpy.data.materials:
            eevee.remove_from_material(m, group)
        ps.eevee_node_group = None
        bpy.data.node_groups.remove(group)
    img = ps.shadow_image
    if img is not None:
        ps.shadow_image = None
        if img.users == 0:
            bpy.data.images.remove(img)
    for child in list(projector.children):
        if child.type == 'LIGHT' or child.get(cleanup.SPOT_KEY) or child.get(body.BODY_KEY):
            cleanup._remove_object(child)

    # Build again.
    spot = create_spot(projector)
    if color is not None:
        spot.data.color = color
    if image_info is not None:
        node = spot.data.node_tree.nodes['Image Texture']
        node.image, node.interpolation, user = image_info
        for a, v in user.items():
            setattr(node.image_user, a, v)
    apply_settings(projector)
    if ps.show_body:
        body.create_body(projector)
    ensure_uid(projector)
    ps.receivers.clear()
    if mats:
        group = eevee.ensure_eevee_node_group(projector)
        for m in mats:
            eevee.repair_material(m)
            eevee.add_to_material(m, group)
            eevee.record_receiver(projector, m)
        if ps.eevee_shadows:
            shadows.bake(projector, _depsgraph(projector))
    return projector
