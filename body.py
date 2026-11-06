"""
Projector body: an optional box for the projector housing.

The projector's origin is the lens. The box sits behind it (the projector
looks down its local -Z axis, so "behind" is +Z), with its front face just
behind the lens. X is the width, Y the height and Z the depth of the box.
The lens offset moves the box sideways and up/down relative to the lens, for
projectors whose lens isn't centred in the housing.

The body is a real mesh, so it shows in the viewport and renders, and it
blocks other projectors' beams in Cycles and in the baked EEVEE shadows. It
never blocks its own projector, because it is entirely behind the lens.

The body can be clicked: when it gets selected, the selection is handed over
to its projector, so it acts like part of the projector.
"""

import bpy

BODY_KEY = 'projectors_body'
MATERIAL_NAME = 'Projector Body'
# Gap between the lens (light origin) and the front face, so the light never
# sits on the box surface.
FRONT_GAP = 0.005


def get_body(projector):
    for child in projector.children:
        if child.type == 'MESH' and child.get(BODY_KEY):
            return child
    return None


def _material():
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL_NAME)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = (0.05, 0.05, 0.055, 1.0)
            bsdf.inputs['Roughness'].default_value = 0.6
        mat.diffuse_color = (0.05, 0.05, 0.055, 1.0)
    return mat


def _box_coords(settings):
    w, h, d = settings.body_size
    ox, oy = settings.body_lens_offset
    # Lens offset = where the lens is relative to the centre of the front face.
    cx, cy = -ox, -oy
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    z0, z1 = FRONT_GAP, FRONT_GAP + d
    return [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]


FACES = [
    (0, 3, 2, 1),  # front (faces the projection, -Z)
    (4, 5, 6, 7),  # back
    (0, 1, 5, 4),  # bottom
    (2, 3, 7, 6),  # top
    (1, 2, 6, 5),  # right
    (0, 4, 7, 3),  # left
]


def create_body(projector):
    settings = projector.proj_settings
    mesh = bpy.data.meshes.new('Projector.Body')
    mesh.from_pydata(_box_coords(settings), [], FACES)
    mesh.materials.append(_material())
    body = bpy.data.objects.new('Projector.Body', mesh)
    body[BODY_KEY] = True
    for coll in projector.users_collection:
        coll.objects.link(body)
    body.parent = projector
    body.matrix_parent_inverse.identity()
    # Clicking the body selects the projector instead, see check_selection().
    body.hide_select = False
    from . import registry
    registry.invalidate()
    return body


def update_body_geometry(projector):
    body = get_body(projector)
    if body is None:
        return
    mesh = body.data
    coords = _box_coords(projector.proj_settings)
    if len(mesh.vertices) != 8:
        mesh.clear_geometry()
        mesh.from_pydata(coords, [], FACES)
    else:
        for v, co in zip(mesh.vertices, coords):
            v.co = co
    mesh.update()


def update_show_body(proj_settings, context):
    projector = proj_settings.id_data
    body = get_body(projector)
    if proj_settings.show_body:
        if body is None:
            create_body(projector)
        else:
            update_body_geometry(projector)
    elif body is not None:
        mesh = body.data
        bpy.data.objects.remove(body, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def update_body_size(proj_settings, context):
    update_body_geometry(proj_settings.id_data)


# ---------------------------------------------------------------------------
# Clicking the body selects its projector
# ---------------------------------------------------------------------------

_scheduled = False


def _bodies():
    from . import registry
    return [o for o in registry.bodies() if o.parent is not None]


def check_selection(depsgraph=None):
    """ Called from the depsgraph handler (selection changes trigger it). """
    global _scheduled
    if _scheduled:
        return
    view_layer = getattr(bpy.context, 'view_layer', None)
    if view_layer is None:
        return
    for o in _bodies():
        if o.hide_select:
            o.hide_select = False   # bodies from older versions
        if o.name in view_layer.objects and o.select_get(view_layer=view_layer):
            _scheduled = True
            bpy.app.timers.register(_redirect, first_interval=0.0)
            return


def _redirect():
    global _scheduled
    _scheduled = False
    view_layer = getattr(bpy.context, 'view_layer', None)
    if view_layer is None:
        return None
    active = view_layer.objects.active
    for o in _bodies():
        if o.name not in view_layer.objects or not o.select_get(view_layer=view_layer):
            continue
        o.select_set(False, view_layer=view_layer)
        projector = o.parent
        if projector.name in view_layer.objects and projector.visible_get(view_layer=view_layer):
            projector.select_set(True, view_layer=view_layer)
            if active == o:
                view_layer.objects.active = projector
        elif active == o:
            view_layer.objects.active = None
    return None


def unregister():
    if bpy.app.timers.is_registered(_redirect):
        bpy.app.timers.unregister(_redirect)
