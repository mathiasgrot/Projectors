"""
EEVEE support for projectors.

EEVEE ignores node trees on lights, so the textured spot light that Cycles uses
only shows up as a plain white spot. To work around this, each projector also
gets a material node group ("_Projector_EEVEE") that does the same projection
math as the light tree. The addon inserts that group into the materials of the
receiving objects.

* The group samples the projected texture in the projector's own space, masks
  it to the projector frustum, and lights the surface with the same inverse
  square falloff and cosine term as the Cycles spot light.
* The group goes into a material through a separate Material Output node whose
  target is EEVEE. The original output is switched to target Cycles, so Cycles
  renders are not affected and nothing gets lit twice.
* Drivers keep the light position, power and render visibility live, so moving,
  animating or hiding the projector updates the EEVEE projection too.
* The real spot light keeps its EEVEE influence factors at 0, so it doesn't
  flood the scene with white light in EEVEE.

Shadows: optional. A depth map is baked per projector by ray casting the scene
from the projector (see shadows.py); the group compares each point's distance
to the projector against it. Bakes are re-done shortly after things stop moving.
"""

import math

import bpy
from bpy.app.handlers import persistent

from .helper import auto_offset
from . import shadows

EEVEE_ENGINES = {'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'}

# Node roles, stored as a custom property on nodes the addon adds to materials.
ROLE_KEY = 'projectors_eevee'
ROLE_GROUP = 'group'
ROLE_ADD = 'add'
ROLE_OUTPUT = 'output'          # EEVEE-only output the addon created
ROLE_SPLIT = 'split_original'   # original output that was switched to Cycles

# Scale between the spot light power (W) and the radiance the group emits.
# Blender's point/spot light: radiant intensity = P / (4*pi) per steradian,
# diffuse reflection divides by pi -> L = albedo * P * cos / (4 * pi^2 * d^2).
# The value was checked against Cycles renders of the original light setup.
POWER_FACTOR = 1.0 / (4.0 * math.pi ** 2)

GROUP_VERSION_KEY = 'projectors_eevee_version'
GROUP_VERSION = 3

RECEIVER_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES'}


def is_eevee(context):
    return context.scene.render.engine in EEVEE_ENGINES


def get_spot(projector):
    for child in projector.children:
        if child.type == 'LIGHT':
            return child
    return None


def mute_spot_in_eevee(spot):
    """ The spot only makes sense with its node tree, which EEVEE ignores. """
    for attr in ('diffuse_factor', 'specular_factor', 'transmission_factor', 'volume_factor'):
        if hasattr(spot.data, attr):
            setattr(spot.data, attr, 0.0)


# ---------------------------------------------------------------------------
# Node group
# ---------------------------------------------------------------------------

def _new_socket(group, name, in_out, socket_type):
    if bpy.app.version >= (4, 0):
        return group.interface.new_socket(name, in_out=in_out, socket_type=socket_type)
    sockets = group.inputs if in_out == 'INPUT' else group.outputs
    return sockets.new(socket_type, name)


def _math(nodes, op, name=None, a=None, b=None, loc=(0, 0)):
    n = nodes.new('ShaderNodeMath')
    n.operation = op
    if name:
        n.name = n.label = name
    if a is not None:
        n.inputs[0].default_value = a
    if b is not None:
        n.inputs[1].default_value = b
    n.location = loc
    return n


def _vmath(nodes, op, loc=(0, 0)):
    n = nodes.new('ShaderNodeVectorMath')
    n.operation = op
    n.location = loc
    return n


def create_eevee_node_group(projector):
    spot = get_spot(projector)
    group = bpy.data.node_groups.new('_Projector_EEVEE', 'ShaderNodeTree')
    albedo = _new_socket(group, 'Albedo', 'INPUT', 'NodeSocketColor')
    albedo.default_value = (0.8, 0.8, 0.8, 1.0)
    _new_socket(group, 'Projection', 'OUTPUT', 'NodeSocketShader')

    nodes = group.nodes
    links = group.links
    pos = auto_offset()

    g_in = nodes.new('NodeGroupInput')
    g_in.location = (0, -900)

    # --- Projector space coordinates (same math as the Cycles light tree) ---
    tc = nodes.new('ShaderNodeTexCoord')
    tc.name = 'proj_coords'
    tc.object = spot
    tc.location = pos(0)

    flip = nodes.new('ShaderNodeMapping')
    flip.vector_type = 'TEXTURE'
    flip.inputs[3].default_value[0] = -1
    flip.inputs[3].default_value[1] = -1
    flip.location = pos(200)

    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = pos(350)
    div_x = _math(nodes, 'DIVIDE', loc=pos(200))
    div_y = _math(nodes, 'DIVIDE', loc=(div_x.location[0], -200))
    com = nodes.new('ShaderNodeCombineXYZ')
    com.inputs['Z'].default_value = 1.0
    com.location = pos(200)

    proj_map = nodes.new('ShaderNodeMapping')
    proj_map.name = 'proj_map'
    proj_map.vector_type = 'TEXTURE'
    proj_map.location = pos(200)

    uv = _vmath(nodes, 'ADD', loc=pos(200))
    uv.name = 'uv'
    uv.inputs[1].default_value = (0.5, 0.5, 0.0)

    links.new(tc.outputs['Object'], flip.inputs['Vector'])
    links.new(flip.outputs['Vector'], sep.inputs['Vector'])
    links.new(sep.outputs['X'], div_x.inputs[0])
    links.new(sep.outputs['Z'], div_x.inputs[1])
    links.new(sep.outputs['Y'], div_y.inputs[0])
    links.new(sep.outputs['Z'], div_y.inputs[1])
    links.new(div_x.outputs[0], com.inputs['X'])
    links.new(div_y.outputs[0], com.inputs['Y'])
    links.new(com.outputs['Vector'], proj_map.inputs['Vector'])
    links.new(proj_map.outputs['Vector'], uv.inputs[0])

    # --- Textures ---
    tex_x = pos(250)[0]
    grid_img = nodes.new('ShaderNodeTexImage')
    grid_img.name = 'grid_img'
    grid_img.extension = 'CLIP'
    grid_img.location = (tex_x, 300)

    checker = nodes.new('ShaderNodeTexChecker')
    checker.name = 'checker'
    checker.inputs['Color1'].default_value = (1, 1, 1, 1)
    checker.inputs['Scale'].default_value = 8
    checker.location = (tex_x, 0)

    custom_img = nodes.new('ShaderNodeTexImage')
    custom_img.name = 'custom_img'
    custom_img.extension = 'CLIP'
    custom_img.location = (tex_x, -300)

    # Pixelated preview: images are sampled once per projector pixel when on.
    pix_res = nodes.new('ShaderNodeCombineXYZ')
    pix_res.name = pix_res.label = 'pix_res'
    pix_res.inputs[2].default_value = 1.0
    pix_res.location = (tex_x - 250, 600)
    pix_mul = _vmath(nodes, 'MULTIPLY', loc=(tex_x - 250, 750))
    pix_floor = _vmath(nodes, 'FLOOR', loc=(tex_x - 100, 750))
    pix_add = _vmath(nodes, 'ADD', loc=(tex_x + 50, 750))
    pix_add.inputs[1].default_value = (0.5, 0.5, 0.0)
    pix_div = _vmath(nodes, 'DIVIDE', loc=(tex_x + 200, 750))
    pix_mix = nodes.new('ShaderNodeMix')
    pix_mix.name = pix_mix.label = 'pix_mix'
    pix_mix.data_type = 'VECTOR'
    pix_mix.inputs[0].default_value = 0.0
    pix_mix.location = (tex_x + 350, 750)
    links.new(uv.outputs['Vector'], pix_mul.inputs[0])
    links.new(pix_res.outputs[0], pix_mul.inputs[1])
    links.new(pix_mul.outputs[0], pix_floor.inputs[0])
    links.new(pix_floor.outputs[0], pix_add.inputs[0])
    links.new(pix_add.outputs[0], pix_div.inputs[0])
    links.new(pix_res.outputs[0], pix_div.inputs[1])
    links.new(uv.outputs['Vector'], pix_mix.inputs[4])
    links.new(pix_div.outputs[0], pix_mix.inputs[5])

    links.new(uv.outputs['Vector'], checker.inputs['Vector'])
    for n in (grid_img, custom_img):
        links.new(pix_mix.outputs[1], n.inputs['Vector'])

    tex_select = nodes.new('NodeReroute')
    tex_select.name = 'tex_select'
    tex_select.location = (pos(300)[0], 0)
    links.new(checker.outputs['Color'], tex_select.inputs[0])

    # --- Frustum mask: 0 <= u <= 1, 0 <= v <= 1 and in front of the projector ---
    mx = pos(200)[0]
    uv_sep = nodes.new('ShaderNodeSeparateXYZ')
    uv_sep.location = (mx, -500)
    links.new(uv.outputs['Vector'], uv_sep.inputs['Vector'])
    u0 = _math(nodes, 'GREATER_THAN', b=0.0, loc=(mx + 200, -450))
    u1 = _math(nodes, 'LESS_THAN', b=1.0, loc=(mx + 200, -520))
    v0 = _math(nodes, 'GREATER_THAN', b=0.0, loc=(mx + 200, -590))
    v1 = _math(nodes, 'LESS_THAN', b=1.0, loc=(mx + 200, -660))
    front = _math(nodes, 'LESS_THAN', b=0.0, loc=(mx + 200, -730))
    links.new(uv_sep.outputs['X'], u0.inputs[0])
    links.new(uv_sep.outputs['X'], u1.inputs[0])
    links.new(uv_sep.outputs['Y'], v0.inputs[0])
    links.new(uv_sep.outputs['Y'], v1.inputs[0])
    # Spot looks down its local -Z axis.
    links.new(sep.outputs['Z'], front.inputs[0])
    mask = u0
    for m in (u1, v0, v1, front):
        mul = _math(nodes, 'MULTIPLY', loc=(m.location[0] + 200, m.location[1]))
        links.new(mask.outputs[0], mul.inputs[0])
        links.new(m.outputs[0], mul.inputs[1])
        mask = mul

    # --- Pixel grid (dark lines between pixels, like the Cycles pixel grid) ---
    gx = mx + 1100
    grid_w = nodes.new('ShaderNodeValue')
    grid_w.name = grid_w.label = 'grid_w'
    grid_w.location = (gx, -900)
    grid_h = nodes.new('ShaderNodeValue')
    grid_h.name = grid_h.label = 'grid_h'
    grid_h.location = (gx, -1000)
    grid_on = nodes.new('ShaderNodeValue')
    grid_on.name = grid_on.label = 'grid_on'
    grid_on.outputs[0].default_value = 0.0
    grid_on.location = (gx, -1100)

    mul_u = _math(nodes, 'MULTIPLY', loc=(gx + 200, -900))
    mul_v = _math(nodes, 'MULTIPLY', loc=(gx + 200, -1000))
    links.new(uv_sep.outputs['X'], mul_u.inputs[0])
    links.new(grid_w.outputs[0], mul_u.inputs[1])
    links.new(uv_sep.outputs['Y'], mul_v.inputs[0])
    links.new(grid_h.outputs[0], mul_v.inputs[1])
    frac_u = _math(nodes, 'FRACT', loc=(gx + 400, -900))
    frac_v = _math(nodes, 'FRACT', loc=(gx + 400, -1000))
    links.new(mul_u.outputs[0], frac_u.inputs[0])
    links.new(mul_v.outputs[0], frac_v.inputs[0])
    line_u = _math(nodes, 'GREATER_THAN', b=0.025, loc=(gx + 600, -900))
    line_v = _math(nodes, 'GREATER_THAN', b=0.025, loc=(gx + 600, -1000))
    links.new(frac_u.outputs[0], line_u.inputs[0])
    links.new(frac_v.outputs[0], line_v.inputs[0])
    cells = _math(nodes, 'MULTIPLY', loc=(gx + 800, -950))
    links.new(line_u.outputs[0], cells.inputs[0])
    links.new(line_v.outputs[0], cells.inputs[1])
    # grid factor = 1 - on * (1 - cells)
    inv = _math(nodes, 'SUBTRACT', a=1.0, loc=(gx + 1000, -950))
    links.new(cells.outputs[0], inv.inputs[1])
    gated = _math(nodes, 'MULTIPLY', loc=(gx + 1200, -1000))
    links.new(grid_on.outputs[0], gated.inputs[0])
    links.new(inv.outputs[0], gated.inputs[1])
    grid_factor = _math(nodes, 'SUBTRACT', a=1.0, loc=(gx + 1400, -1000))
    links.new(gated.outputs[0], grid_factor.inputs[1])

    # --- Lighting: power * cos / d^2 ---
    lx = mx
    geo = nodes.new('ShaderNodeNewGeometry')
    geo.location = (lx, -1300)
    light_pos = nodes.new('ShaderNodeCombineXYZ')
    light_pos.name = light_pos.label = 'light_pos'
    light_pos.location = (lx, -1600)
    power = nodes.new('ShaderNodeValue')
    power.name = power.label = 'power'
    power.location = (lx, -1750)

    to_light = _vmath(nodes, 'SUBTRACT', loc=(lx + 200, -1450))
    links.new(light_pos.outputs[0], to_light.inputs[0])
    links.new(geo.outputs['Position'], to_light.inputs[1])
    dist2 = _vmath(nodes, 'DOT_PRODUCT', loc=(lx + 400, -1550))
    links.new(to_light.outputs[0], dist2.inputs[0])
    links.new(to_light.outputs[0], dist2.inputs[1])
    l_dir = _vmath(nodes, 'NORMALIZE', loc=(lx + 400, -1400))
    links.new(to_light.outputs[0], l_dir.inputs[0])
    cos = _vmath(nodes, 'DOT_PRODUCT', loc=(lx + 600, -1350))
    links.new(geo.outputs['Normal'], cos.inputs[0])
    links.new(l_dir.outputs[0], cos.inputs[1])
    cos_pos = _math(nodes, 'MAXIMUM', b=0.0, loc=(lx + 800, -1350))
    links.new(cos.outputs['Value'], cos_pos.inputs[0])
    irr = _math(nodes, 'DIVIDE', loc=(lx + 1000, -1400))
    links.new(cos_pos.outputs[0], irr.inputs[0])
    links.new(dist2.outputs['Value'], irr.inputs[1])
    irr_p = _math(nodes, 'MULTIPLY', loc=(lx + 1200, -1450))
    links.new(irr.outputs[0], irr_p.inputs[0])
    links.new(power.outputs[0], irr_p.inputs[1])

    # --- Combine ---
    scalar = _math(nodes, 'MULTIPLY', loc=(gx + 1600, -700))
    links.new(mask.outputs[0], scalar.inputs[0])
    links.new(grid_factor.outputs[0], scalar.inputs[1])
    scalar2 = _math(nodes, 'MULTIPLY', loc=(gx + 1800, -700))
    links.new(scalar.outputs[0], scalar2.inputs[0])
    links.new(irr_p.outputs[0], scalar2.inputs[1])

    tinted = _vmath(nodes, 'MULTIPLY', loc=(gx + 1600, 0))
    links.new(tex_select.outputs[0], tinted.inputs[0])
    links.new(g_in.outputs['Albedo'], tinted.inputs[1])
    scaled = _vmath(nodes, 'SCALE', loc=(gx + 1800, 0))
    links.new(tinted.outputs[0], scaled.inputs[0])
    # --- Shadows: compare the distance to the projector with a baked depth map ---
    sx = gx + 1600
    shadow_tex = nodes.new('ShaderNodeTexImage')
    shadow_tex.name = 'shadow_tex'
    shadow_tex.interpolation = 'Closest'
    shadow_tex.extension = 'EXTEND'
    shadow_tex.location = (sx, -1300)
    links.new(uv.outputs['Vector'], shadow_tex.inputs['Vector'])
    shadow_sep = nodes.new('ShaderNodeSeparateColor')
    shadow_sep.location = (sx + 300, -1300)
    links.new(shadow_tex.outputs['Color'], shadow_sep.inputs['Color'])
    shadow_bias = nodes.new('ShaderNodeValue')
    shadow_bias.name = shadow_bias.label = 'shadow_bias'
    shadow_bias.outputs[0].default_value = 1.02
    shadow_bias.location = (sx + 300, -1500)
    # threshold = baked distance * (1 + bias) + 1 cm
    threshold = _math(nodes, 'MULTIPLY_ADD', loc=(sx + 500, -1350))
    threshold.inputs[2].default_value = 0.01
    links.new(shadow_sep.outputs['Red'], threshold.inputs[0])
    links.new(shadow_bias.outputs[0], threshold.inputs[1])
    dist = _math(nodes, 'SQRT', loc=(sx + 500, -1550))
    links.new(dist2.outputs['Value'], dist.inputs[0])
    lit = _math(nodes, 'LESS_THAN', loc=(sx + 700, -1400))
    links.new(dist.outputs[0], lit.inputs[0])
    links.new(threshold.outputs[0], lit.inputs[1])
    shadow_on = nodes.new('ShaderNodeValue')
    shadow_on.name = shadow_on.label = 'shadow_on'
    shadow_on.outputs[0].default_value = 0.0
    shadow_on.location = (sx + 700, -1600)
    # shadow factor = 1 - on * (1 - lit)
    s_inv = _math(nodes, 'SUBTRACT', a=1.0, loc=(sx + 900, -1400))
    links.new(lit.outputs[0], s_inv.inputs[1])
    s_gated = _math(nodes, 'MULTIPLY', loc=(sx + 1100, -1450))
    links.new(shadow_on.outputs[0], s_gated.inputs[0])
    links.new(s_inv.outputs[0], s_gated.inputs[1])
    s_factor = _math(nodes, 'SUBTRACT', a=1.0, loc=(sx + 1300, -1450))
    links.new(s_gated.outputs[0], s_factor.inputs[1])
    scalar3 = _math(nodes, 'MULTIPLY', loc=(gx + 2000, -700))
    links.new(scalar2.outputs[0], scalar3.inputs[0])
    links.new(s_factor.outputs[0], scalar3.inputs[1])

    links.new(scalar3.outputs[0], scaled.inputs['Scale'])

    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1.0
    emission.location = (gx + 2000, 0)
    links.new(scaled.outputs[0], emission.inputs['Color'])
    g_out = nodes.new('NodeGroupOutput')
    g_out.location = (gx + 2200, 0)
    links.new(emission.outputs[0], g_out.inputs[0])

    _add_drivers(group, projector, spot)
    group[GROUP_VERSION_KEY] = GROUP_VERSION
    return group


def _add_drivers(group, projector, spot):
    for i, axis in enumerate('XYZ'):
        fc = group.driver_add(f'nodes["light_pos"].inputs[{i}].default_value')
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = 'loc'
        var = drv.variables.new()
        var.name = 'loc'
        var.type = 'TRANSFORMS'
        var.targets[0].id = spot
        var.targets[0].transform_type = f'LOC_{axis}'
        var.targets[0].transform_space = 'WORLD_SPACE'

    fc = group.driver_add('nodes["power"].outputs[0].default_value')
    drv = fc.driver
    drv.type = 'SCRIPTED'
    # Simple expression: evaluated without Python, so it works even with
    # "Auto Run Python Scripts" disabled.
    drv.expression = f'energy * {POWER_FACTOR:.10f} * (1 - hidden)'
    var = drv.variables.new()
    var.name = 'energy'
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'LIGHT'
    var.targets[0].id = spot.data
    var.targets[0].data_path = 'energy'
    var = drv.variables.new()
    var.name = 'hidden'
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'OBJECT'
    var.targets[0].id = projector
    var.targets[0].data_path = 'hide_render'


def ensure_eevee_node_group(projector):
    settings = projector.proj_settings
    group = settings.eevee_node_group
    if group is None:
        spot = get_spot(projector)
        mute_spot_in_eevee(spot)
        group = create_eevee_node_group(projector)
        settings.eevee_node_group = group
    elif group.get(GROUP_VERSION_KEY, 1) < GROUP_VERSION:
        group = _upgrade_group(projector, group)
    sync(projector)
    return group


def _upgrade_group(projector, old):
    """ Rebuild a group made by an older version and swap it into every material using it. """
    new = create_eevee_node_group(projector)
    for mat in bpy.data.materials:
        if mat.node_tree:
            for n in mat.node_tree.nodes:
                if n.type == 'GROUP' and n.node_tree == old:
                    n.node_tree = new
    projector.proj_settings.eevee_node_group = new
    name = old.name
    bpy.data.node_groups.remove(old)
    new.name = name
    return new


# ---------------------------------------------------------------------------
# Keeping the EEVEE group in step with the Cycles light tree
# ---------------------------------------------------------------------------

def _set(obj, attr, value):
    if getattr(obj, attr) != value:
        setattr(obj, attr, value)


def _set_vec(socket, value):
    if tuple(socket.default_value) != tuple(value):
        socket.default_value = value


def _link(tree, from_socket, to_socket):
    for l in to_socket.links:
        if l.from_socket == from_socket:
            return
    tree.links.new(from_socket, to_socket)


def sync(projector):
    """ Copy the projector state from its Cycles light tree to the EEVEE group.
    Only writes values that changed, so it's safe to call from update handlers. """
    settings = projector.proj_settings
    group = settings.eevee_node_group
    spot = get_spot(projector)
    if group is None or spot is None or spot.data.node_tree is None:
        return
    root = spot.data.node_tree
    try:
        cyc_nodes = root.nodes['Group'].node_tree.nodes
        nodes = group.nodes
        _set(nodes['proj_coords'], 'object', spot)

        src_map = cyc_nodes['Mapping.001']
        _set_vec(nodes['proj_map'].inputs[1], src_map.inputs[1].default_value)
        _set_vec(nodes['proj_map'].inputs[3], src_map.inputs[3].default_value)

        _set(nodes['grid_img'], 'image', cyc_nodes['Image Texture'].image)
        _set_vec(nodes['checker'].inputs['Color2'],
                 cyc_nodes['Checker Texture'].inputs['Color2'].default_value)

        src_custom = root.nodes['Image Texture']
        dst_custom = nodes['custom_img']
        _set(dst_custom, 'image', src_custom.image)
        # Pixelated preview: unfiltered sampling, or EEVEE's filtering blurs the cell edges.
        _set(dst_custom, 'interpolation',
             'Closest' if settings.show_pixel_grid else src_custom.interpolation)
        for attr in ('frame_duration', 'frame_start', 'frame_offset',
                     'use_cyclic', 'use_auto_refresh'):
            _set(dst_custom.image_user, attr, getattr(src_custom.image_user, attr))

        case = settings.projected_texture
        if case == 'checker_texture':
            src = nodes['checker'].outputs['Color']
        elif case == 'color_grid_texture':
            src = nodes['grid_img'].outputs['Color']
        else:
            src = nodes['custom_img'].outputs['Color']
        _link(group, src, nodes['tex_select'].inputs[0])

        pg = root.nodes['pixel_grid'].node_tree.nodes
        _set(nodes['grid_w'].outputs[0], 'default_value', pg['_width'].outputs[0].default_value)
        _set(nodes['grid_h'].outputs[0], 'default_value', pg['_height'].outputs[0].default_value)
        _set(nodes['grid_on'].outputs[0], 'default_value', 1.0 if settings.show_pixel_grid else 0.0)

        if 'pix_mix' in nodes:
            _set(nodes['pix_res'].inputs[0], 'default_value', pg['_width'].outputs[0].default_value)
            _set(nodes['pix_res'].inputs[1], 'default_value', pg['_height'].outputs[0].default_value)
            _set(nodes['pix_mix'].inputs[0], 'default_value', 1.0 if settings.show_pixel_grid else 0.0)
            _set(nodes['grid_img'], 'interpolation', 'Closest' if settings.show_pixel_grid else 'Linear')

        if 'shadow_tex' in nodes:
            img = settings.shadow_image
            _set(nodes['shadow_tex'], 'image', img)
            on = settings.eevee_shadows and img is not None
            _set(nodes['shadow_on'].outputs[0], 'default_value', 1.0 if on else 0.0)
            _set(nodes['shadow_bias'].outputs[0], 'default_value', 1.0 + settings.shadow_bias)
    except KeyError:
        # Node setup was edited by hand; leave it alone.
        pass


def all_projectors():
    return [o for o in bpy.data.objects
            if o.type == 'CAMERA' and o.name.startswith('Projector')
            and o.proj_settings.eevee_node_group is not None]


_syncing = False


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    global _syncing
    if _syncing:
        return
    _syncing = True
    try:
        from . import duplicate, cleanup, body
        duplicate.check(depsgraph)
        cleanup.check(depsgraph)
        body.check_selection(depsgraph)
        for projector in all_projectors():
            sync(projector)
        if depsgraph is not None:
            shadows.on_depsgraph_update(depsgraph)
    finally:
        _syncing = False


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def _role(node):
    try:
        return node.get(ROLE_KEY)
    except TypeError:
        return None


def _get_eevee_output(mat):
    nt = mat.node_tree
    out = nt.get_output_node('EEVEE')
    if out is None:
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        out.target = 'EEVEE'
        out[ROLE_KEY] = ROLE_OUTPUT
        out.location = (300, 300)
        return out
    if out.target == 'ALL':
        # Split: keep the original for Cycles, add an EEVEE-only copy.
        out.target = 'CYCLES'
        out[ROLE_KEY] = ROLE_SPLIT
        new = nt.nodes.new('ShaderNodeOutputMaterial')
        new.target = 'EEVEE'
        new[ROLE_KEY] = ROLE_OUTPUT
        new.location = (out.location[0], out.location[1] + 300)
        for sock in out.inputs:
            for l in sock.links:
                nt.links.new(l.from_socket, new.inputs[sock.identifier])
        new.is_active_output = True
        out = new
    return out


def _albedo_source(node):
    """ Find what defines the surface color of the shader that feeds the output. """
    if node is None:
        return None
    for name in ('Base Color', 'Color'):
        if name in node.inputs and node.type in {'BSDF_PRINCIPLED', 'BSDF_DIFFUSE'}:
            return node.inputs[name]
    return None


def material_has_projector(mat, group):
    if not mat or not mat.node_tree:
        return False
    return any(n.type == 'GROUP' and n.node_tree == group and _role(n) == ROLE_GROUP
               for n in mat.node_tree.nodes)


def add_to_material(mat, group):
    if mat.node_tree is None:
        mat.use_nodes = True
    if material_has_projector(mat, group):
        return False
    nt = mat.node_tree
    out = _get_eevee_output(mat)
    surface = out.inputs['Surface']
    src = surface.links[0].from_socket if surface.links else None

    loc = out.location
    gnode = nt.nodes.new('ShaderNodeGroup')
    gnode.node_tree = group
    gnode.label = 'Projector (EEVEE)'
    gnode[ROLE_KEY] = ROLE_GROUP
    gnode.location = (loc[0] - 200, loc[1] + 250)
    add = nt.nodes.new('ShaderNodeAddShader')
    add[ROLE_KEY] = ROLE_ADD
    add.location = (loc[0] - 20, loc[1] + 120)
    add.hide = True

    if src is not None:
        nt.links.new(src, add.inputs[0])
    nt.links.new(gnode.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], surface)

    # Use the material's own surface color, so a red wall gets a red-tinted
    # projection the way it would in Cycles. Follows chains of earlier
    # projector Add Shaders back to the actual BSDF.
    shader = src.node if src is not None else None
    while shader is not None and _role(shader) == ROLE_ADD:
        links = shader.inputs[0].links
        shader = links[0].from_node if links else None
    albedo = _albedo_source(shader)
    if albedo is not None:
        if albedo.links:
            nt.links.new(albedo.links[0].from_socket, gnode.inputs['Albedo'])
        else:
            gnode.inputs['Albedo'].default_value = albedo.default_value
    return True


def remove_from_material(mat, group=None):
    """ Remove one projector (or all, if group is None) from a material. """
    if not mat or not mat.node_tree:
        return False
    nt = mat.node_tree
    removed = False
    for gnode in [n for n in nt.nodes if _role(n) == ROLE_GROUP]:
        if group is False or (group is not None and gnode.node_tree != group):
            continue
        for l in list(gnode.outputs[0].links):
            add = l.to_node
            if _role(add) != ROLE_ADD:
                continue
            upstream = add.inputs[0].links[0].from_socket if add.inputs[0].links else None
            downstream = [dl.to_socket for dl in add.outputs[0].links]
            nt.nodes.remove(add)
            if upstream is not None:
                for sock in downstream:
                    nt.links.new(upstream, sock)
        nt.nodes.remove(gnode)
        removed = True

    if not any(_role(n) == ROLE_GROUP for n in nt.nodes):
        # Restore the original single output.
        for n in list(nt.nodes):
            if _role(n) == ROLE_OUTPUT:
                nt.nodes.remove(n)
        for n in nt.nodes:
            if _role(n) == ROLE_SPLIT:
                n.target = 'ALL'
                del n[ROLE_KEY]
                n.is_active_output = True
    return removed


def _object_materials(obj, create=False):
    if obj.type not in RECEIVER_TYPES or not hasattr(obj.data, 'materials'):
        return []
    mats = obj.data.materials
    if create:
        if len(mats) == 0:
            mats.append(_default_material())
        else:
            for i, m in enumerate(mats):
                if m is None:
                    mats[i] = _default_material()
    return [m for m in mats if m is not None]


def _default_material():
    """ Matches Blender's look for objects without a material. """
    mat = bpy.data.materials.get('Projector Receiver')
    if mat is None:
        mat = bpy.data.materials.new('Projector Receiver')
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        diffuse = nt.nodes.new('ShaderNodeBsdfDiffuse')
        diffuse.inputs['Color'].default_value = (0.8, 0.8, 0.8, 1.0)
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        out.location = (300, 0)
        nt.links.new(diffuse.outputs[0], out.inputs['Surface'])
    return mat


def record_receiver(projector, mat):
    recs = projector.proj_settings.receivers
    if not any(r.material == mat for r in recs):
        recs.add().material = mat


def unrecord_receiver(projector, mat):
    recs = projector.proj_settings.receivers
    for i in reversed(range(len(recs))):
        if recs[i].material == mat or recs[i].material is None:
            recs.remove(i)


def recorded_receivers(projector):
    return [r.material for r in projector.proj_settings.receivers if r.material is not None]


def add_receivers(projector, objects):
    group = ensure_eevee_node_group(projector)
    count = 0
    for obj in objects:
        if obj == projector or obj.parent == projector:
            continue
        for mat in _object_materials(obj, create=True):
            if add_to_material(mat, group):
                count += 1
            record_receiver(projector, mat)
    return count


def repair_material(mat):
    """ Remove leftovers of projectors whose node was deleted by hand: Add Shaders
    with nothing in their projector input, and the extra output if nothing's left. """
    if not mat or not mat.node_tree:
        return
    nt = mat.node_tree
    for add in [n for n in nt.nodes if _role(n) == ROLE_ADD]:
        if add.inputs[1].links and _role(add.inputs[1].links[0].from_node) == ROLE_GROUP:
            continue
        upstream = add.inputs[0].links[0].from_socket if add.inputs[0].links else None
        downstream = [l.to_socket for l in add.outputs[0].links]
        nt.nodes.remove(add)
        if upstream is not None:
            for sock in downstream:
                nt.links.new(upstream, sock)
    remove_from_material(mat, group=False)


def remove_receivers(projector, objects=None):
    group = projector.proj_settings.eevee_node_group
    if group is None:
        return 0
    if objects is None:
        mats = list(bpy.data.materials)
    else:
        mats = {m for o in objects for m in _object_materials(o)}
    count = 0
    for m in mats:
        if remove_from_material(m, group):
            count += 1
        unrecord_receiver(projector, m)
    return count


def receiver_count(projector):
    group = projector.proj_settings.eevee_node_group
    if group is None:
        return 0
    return sum(1 for m in bpy.data.materials if material_has_projector(m, group))


def remove_projector(projector):
    """ Clean up everything EEVEE related before a projector is deleted. """
    group = projector.proj_settings.eevee_node_group
    if group is None:
        return
    remove_receivers(projector)
    projector.proj_settings.eevee_node_group = None
    bpy.data.node_groups.remove(group)
    img = projector.proj_settings.shadow_image
    if img is not None:
        projector.proj_settings.shadow_image = None
        bpy.data.images.remove(img)


@persistent
def _on_load(*args):
    # Upgrade groups made by older versions, then sync.
    for projector in all_projectors():
        try:
            ensure_eevee_node_group(projector)
        except Exception as e:
            print(f'[Projectors Addon]: could not update EEVEE setup of {projector.name}: {e}')


def register():
    shadows.register()
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    shadows.unregister()
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
