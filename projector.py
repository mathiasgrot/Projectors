import logging
import math
import os

from enum import Enum
import bpy
import mathutils
from bpy.types import Operator

from .helper import (ADDON_ID, auto_offset,
                     get_projectors, get_projector, get_spot, random_color)
from . import eevee, shadows, body, duplicate, cleanup, presets

logging.basicConfig(
    format='[Projectors Addon]: %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(name=__file__)


class Textures(Enum):
    CHECKER = 'checker_texture'
    COLOR_GRID = 'color_grid_texture'
    CUSTOM_TEXTURE = 'custom_texture'


RESOLUTIONS = [
    # 16:10 aspect ratio
    ('1280x800', 'WXGA (1280x800) 16:10', '', 1),
    ('1440x900', 'WXGA+ (1440x900) 16:10', '', 2),
    ('1920x1200', 'WUXGA (1920x1200) 16:10', '', 3),
    ('2560x1600', 'WQXGA (2560x1600) 16:10', '', 13),
    ('3840x2400', 'WQUXGA (3840x2400) 16:10', '', 14),
    # 16:9 aspect ratio
    ('1280x720', '720p (1280x720) 16:9', '', 4),
    ('1920x1080', '1080p (1920x1080) 16:9', '', 5),
    ('3840x2160', '4K Ultra HD (3840x2160) 16:9', '', 6),
    # 4:3 aspect ratio
    ('800x600', 'SVGA (800x600) 4:3', '', 7),
    ('1024x768', 'XGA (1024x768) 4:3', '', 8),
    ('1400x1050', 'SXGA+ (1400x1050) 4:3', '', 9),
    ('1600x1200', 'UXGA (1600x1200) 4:3', '', 10),
    # 17:9 aspect ratio
    ('4096x2160', 'Native 4K (4096x2160) 17:9', '', 11),
    # 1:1 aspect ratio
    ('1000x1000', 'Square (1000x1000) 1:1', '', 12),
    # Any size
    ('custom', 'Custom', 'Set your own width and height', 99),
]

PROJECTED_OUTPUTS = [(Textures.CHECKER.value, 'Checker', '', 1),
                     (Textures.COLOR_GRID.value, 'Color Grid', '', 2),
                     (Textures.CUSTOM_TEXTURE.value, 'Custom Texture', '', 3)]


class PROJECTOR_OT_change_color_randomly(Operator):
    """ Randomly change the color of the projected checker texture."""
    bl_idname = 'projector.change_color'
    bl_label = 'Change color of projection checker texture'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(get_projectors(context, only_selected=True)) == 1

    def execute(self, context):
        projectors = get_projectors(context, only_selected=True)
        new_color = random_color(alpha=True)
        for projector in projectors:
            projector.proj_settings['projected_color'] = new_color[:-1]
            update_checker_color(projector.proj_settings, context)
        return {'FINISHED'}


def create_projector_textures():
    """ This function checks if the needed images exist and if not creates them. """
    for res in RESOLUTIONS:
        if res[0] == 'custom':
            continue
        w, h = res[0].split('x')
        ensure_resolution_texture(int(w), int(h))


def ensure_resolution_texture(w, h):
    """ The colour grid image for one resolution, created on demand. """
    img_name = f'_proj.tex.{int(w)}x{int(h)}'
    img = bpy.data.images.get(img_name)
    if img is None:
        log.debug(f'Create projection texture: {img_name}')
        img = bpy.data.images.new(img_name, int(w), int(h), alpha=True)
        img.generated_type = 'COLOR_GRID'
    img.use_fake_user = True
    return img


def add_projector_node_tree_to_spot(spot):
    """
    This function turns a spot light into a projector.
    This is achieved through a texture on the spot light and some basic math.
    """

    spot.data.use_nodes = True
    root_tree = spot.data.node_tree
    root_tree.nodes.clear()

    node_group = bpy.data.node_groups.new('_Projector', 'ShaderNodeTree')

    # Create output sockets for the node group.
    if(bpy.app.version >= (4, 0)):
        node_group.interface.new_socket('texture vector',  in_out="OUTPUT", socket_type='NodeSocketVector')
        node_group.interface.new_socket('color', in_out="OUTPUT", socket_type='NodeSocketColor')
    else:
        output = node_group.outputs
        output.new('NodeSocketVector', 'texture vector')
        output.new('NodeSocketColor', 'color')

    # # Inside Group Node #
    # #####################

    # Hold important nodes inside a group node.
    group = spot.data.node_tree.nodes.new('ShaderNodeGroup')
    group.node_tree = node_group
    group.label = "!! Don't touch !!"

    nodes = group.node_tree.nodes
    tree = group.node_tree

    auto_pos = auto_offset()

    tex = nodes.new('ShaderNodeTexCoord')
    tex.location = auto_pos(200)

    geo = nodes.new('ShaderNodeNewGeometry')
    geo.location = auto_pos(0, -300)
    vec_transform = nodes.new('ShaderNodeVectorTransform')
    vec_transform.location = auto_pos(200)
    vec_transform.vector_type = 'NORMAL'

    map_1 = nodes.new('ShaderNodeMapping')
    map_1.vector_type = 'TEXTURE'
    # Flip the image horizontally and vertically to display it the intended way.
    if bpy.app.version < (2, 81):
        map_1.scale[0] = -1
        map_1.scale[1] = -1
    else:
        map_1.inputs[3].default_value[0] = -1
        map_1.inputs[3].default_value[1] = -1
    map_1.location = auto_pos(200)

    sep = nodes.new('ShaderNodeSeparateXYZ')
    sep.location = auto_pos(350)

    div_1 = nodes.new('ShaderNodeMath')
    div_1.operation = 'DIVIDE'
    div_1.name = ADDON_ID + 'div_01'
    div_1.location = auto_pos(200)

    div_2 = nodes.new('ShaderNodeMath')
    div_2.operation = 'DIVIDE'
    div_2.name = ADDON_ID + 'div_02'
    div_2.location = auto_pos(y=-200)

    com = nodes.new('ShaderNodeCombineXYZ')
    com.inputs['Z'].default_value = 1.0
    com.location = auto_pos(200)

    map_2 = nodes.new('ShaderNodeMapping')
    map_2.location = auto_pos(200)
    map_2.vector_type = 'TEXTURE'

    add = nodes.new('ShaderNodeMixRGB')
    add.blend_type = 'ADD'
    add.inputs[0].default_value = 1
    add.location = auto_pos(350)

    # Texture
    # a) Image
    img = nodes.new('ShaderNodeTexImage')
    img.extension = 'CLIP'
    img.location = auto_pos(200)

    # b) Generated checker texture.
    checker_tex = nodes.new('ShaderNodeTexChecker')
    # checker_tex.inputs['Color2'].default_value = random_color(alpha=True)
    checker_tex.inputs[3].default_value = 8
    checker_tex.inputs[1].default_value = (1, 1, 1, 1)
    checker_tex.location = auto_pos(y=-300)

    mix_rgb = nodes.new('ShaderNodeMixRGB')
    mix_rgb.name = 'Mix.001'
    mix_rgb.inputs[1].default_value = (0, 0, 0, 0)
    mix_rgb.location = auto_pos(200, y=-300)

    group_output_node = node_group.nodes.new('NodeGroupOutput')
    group_output_node.location = auto_pos(200)

    # # Root Nodes #
    # ##############
    auto_pos_root = auto_offset()
    # Image Texture
    user_texture = root_tree.nodes.new('ShaderNodeTexImage')
    user_texture.extension = 'CLIP'
    user_texture.label = 'Add your Image Texture or Movie here'
    user_texture.location = auto_pos_root(200, y=200)
    # Emission
    emission = root_tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1
    emission.location = auto_pos_root(300)
    # Material Output
    output = root_tree.nodes.new('ShaderNodeOutputLight')
    output.location = auto_pos_root(200)

    # # LINK NODES #
    # ##############

    # Link inside group node
    if(bpy.app.version >= (4, 0)):
        tree.links.new(geo.outputs['Incoming'], vec_transform.inputs['Vector'])
        tree.links.new(vec_transform.outputs['Vector'], map_1.inputs['Vector'])
    else:
        tree.links.new(tex.outputs['Normal'], map_1.inputs['Vector'])
    tree.links.new(map_1.outputs['Vector'], sep.inputs['Vector'])

    tree.links.new(sep.outputs[0], div_1.inputs[0])  # X -> value0
    tree.links.new(sep.outputs[2], div_1.inputs[1])  # Z -> value1
    tree.links.new(sep.outputs[1], div_2.inputs[0])  # Y -> value0
    tree.links.new(sep.outputs[2], div_2.inputs[1])  # Z -> value1

    tree.links.new(div_1.outputs[0], com.inputs[0])
    tree.links.new(div_2.outputs[0], com.inputs[1])

    tree.links.new(com.outputs['Vector'], map_2.inputs['Vector'])

    # Textures
    # a) generated texture
    tree.links.new(map_2.outputs['Vector'], add.inputs['Color1'])
    tree.links.new(add.outputs['Color'], img.inputs['Vector'])
    tree.links.new(add.outputs['Color'], group_output_node.inputs[0])
    # b) checker texture
    tree.links.new(add.outputs['Color'], checker_tex.inputs['Vector'])
    tree.links.new(img.outputs['Alpha'], mix_rgb.inputs[0])
    tree.links.new(checker_tex.outputs['Color'], mix_rgb.inputs[2])

    # Link in root
    root_tree.links.new(group.outputs['texture vector'], user_texture.inputs['Vector'])
    root_tree.links.new(group.outputs['color'], emission.inputs['Color'])
    root_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])

    # Pixel Grid Setup
    pixel_grid_group = create_pixel_grid_node_group()
    pixel_grid_node = spot.data.node_tree.nodes.new('ShaderNodeGroup')
    pixel_grid_node.node_tree = pixel_grid_group
    pixel_grid_node.label = "Pixel Grid"
    pixel_grid_node.name = 'pixel_grid'
    loc = root_tree.nodes['Emission'].location
    pixel_grid_node.location = (loc[0], loc[1] - 150)

    root_tree.links.new(group.outputs[0], pixel_grid_node.inputs[1])
    root_tree.links.new(emission.outputs[0], pixel_grid_node.inputs[0])

def get_resolution(proj_settings, context):
    """ Find out what resolution is currently used and return it.
    Resolution from the dropdown or the resolution from the custom texture.
    """
    return get_resolution_for(proj_settings.id_data)


def get_resolution_for(projector):
    """ Same as get_resolution, for a given projector instead of the selected one. """
    settings = projector.proj_settings
    if settings.use_custom_texture_res and settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
        image = get_spot(projector).data.node_tree.nodes['Image Texture'].image
        if image and image.size[0] and image.size[1]:
            return float(image.size[0]), float(image.size[1])
        return 300.0, 300.0
    return get_preset_resolution(settings)


def get_preset_resolution(settings):
    """ The chosen resolution, ignoring the custom texture. """
    if settings.resolution == 'custom':
        w, h = settings.custom_resolution
        return float(max(1, w)), float(max(1, h))
    w, h = settings.resolution.split('x')
    return float(w), float(h)


def _aspect(settings):
    w, h = get_resolution_for(settings.id_data)
    return w / h if h else 1.0


def get_image_width(self):
    return self.plan_distance / max(self.throw_ratio, 1e-6)


def set_image_width(self, value):
    value = max(value, 1e-4)
    if self.plan_solve == 'THROW':
        self.throw_ratio = self.plan_distance / value
    else:
        self.plan_distance = self.throw_ratio * value


def get_image_height(self):
    return get_image_width(self) / _aspect(self)


def set_image_height(self, value):
    set_image_width(self, value * _aspect(self))


def get_image_diagonal(self):
    a = _aspect(self)
    return get_image_width(self) * math.sqrt(1 + 1 / (a * a))


def set_image_diagonal(self, value):
    a = _aspect(self)
    set_image_width(self, value / math.sqrt(1 + 1 / (a * a)))


def get_zoom(self):
    lo, hi = sorted(self.throw_limits)
    if hi - lo < 1e-6:
        return 0.0
    return (self.throw_ratio - lo) / (hi - lo) * 100.0


def set_zoom(self, value):
    lo, hi = sorted(self.throw_limits)
    self.throw_ratio = lo + (hi - lo) * min(max(value, 0.0), 100.0) / 100.0


def update_limits(proj_settings, context):
    update_throw_ratio(proj_settings, context)


def update_eevee_shadows(proj_settings, context):
    projector = proj_settings.id_data
    if proj_settings.eevee_shadows and proj_settings.eevee_node_group is not None:
        eevee.ensure_eevee_node_group(projector)
        shadows.bake(projector, context.evaluated_depsgraph_get())
    eevee.sync(projector)


def update_shadow_bias(proj_settings, context):
    eevee.sync(proj_settings.id_data)


def update_shadow_resolution(proj_settings, context):
    projector = proj_settings.id_data
    if proj_settings.eevee_shadows and proj_settings.eevee_node_group is not None:
        shadows.bake(projector, context.evaluated_depsgraph_get())


def update_throw_ratio(proj_settings, context):
    """
    Adjust some settings on a camera to achieve a throw ratio
    """
    projector = proj_settings.id_data
    # Keep the throw ratio inside the lens range, if the lens has one.
    throw_ratio = proj_settings.get('throw_ratio', proj_settings.throw_ratio)
    if proj_settings.limit_throw:
        lo, hi = sorted(proj_settings.throw_limits)
        clamped = min(max(throw_ratio, lo), hi)
        if clamped != throw_ratio:
            proj_settings['throw_ratio'] = clamped
            throw_ratio = clamped
    # Update properties of the camera.
    distance = 1
    alpha = math.atan((distance/throw_ratio)*.5) * 2
    projector.data.lens_unit = 'FOV'
    projector.data.angle = alpha
    projector.data.sensor_width = 10
    projector.data.display_size = 1

    # Adjust Texture to fit new camera ###
    w, h = get_resolution(proj_settings, context)
    aspect_ratio = w/h
    inverted_aspect_ratio = 1/aspect_ratio

    # Projected Texture
    update_projected_texture(proj_settings, context)

    # Update spotlight properties.
    spot = get_spot(projector)
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    if bpy.app.version < (2, 81):
        nodes['Mapping.001'].scale[0] = 1 / throw_ratio
        nodes['Mapping.001'].scale[1] = 1 / throw_ratio * inverted_aspect_ratio
    else:
        nodes['Mapping.001'].inputs[3].default_value[0] = 1 / throw_ratio
        nodes['Mapping.001'].inputs[3].default_value[1] = 1 / \
            throw_ratio * inverted_aspect_ratio

    # Update lens shift because it depends on the throw ratio.
    update_lens_shift(proj_settings, context)
    eevee.sync(projector)

    


def update_lens_shift(proj_settings, context):
    """
    Apply the shift to the camera and texture.
    """
    projector = proj_settings.id_data
    if proj_settings.limit_shift:
        for key, limits in (('h_shift', proj_settings.h_shift_limits),
                            ('v_shift', proj_settings.v_shift_limits)):
            lo, hi = sorted(limits)
            value = proj_settings.get(key, 0.0)
            if not lo <= value <= hi:
                proj_settings[key] = min(max(value, lo), hi)
    h_shift = proj_settings.get('h_shift', 0.0) / 100
    v_shift = proj_settings.get('v_shift', 0.0) / 100
    throw_ratio = proj_settings.get('throw_ratio', proj_settings.throw_ratio)

    w, h = get_resolution(proj_settings, context)
    inverted_aspect_ratio = h/w

    # Update the properties of the camera.
    cam = projector
    cam.data.shift_x = h_shift
    cam.data.shift_y = v_shift * inverted_aspect_ratio

    # Update spotlight node setup.
    spot = get_spot(projector)
    nodes = spot.data.node_tree.nodes['Group'].node_tree.nodes
    if bpy.app.version < (2, 81):
        nodes['Mapping.001'].translation[0] = h_shift / throw_ratio
        nodes['Mapping.001'].translation[1] = v_shift / throw_ratio * inverted_aspect_ratio
    else:
        nodes['Mapping.001'].inputs[1].default_value[0] = h_shift / throw_ratio
        nodes['Mapping.001'].inputs[1].default_value[1] = v_shift / throw_ratio * inverted_aspect_ratio
    eevee.sync(projector)


def update_resolution(proj_settings, context):
    projector = proj_settings.id_data
    nodes = get_spot(projector).data.node_tree.nodes['Group'].node_tree.nodes
    # Change resolution image texture
    w, h = get_preset_resolution(proj_settings)
    nodes['Image Texture'].image = ensure_resolution_texture(w, h)
    update_throw_ratio(proj_settings, context)
    update_pixel_grid(proj_settings, context)


def update_checker_color(proj_settings, context):
    # Update checker texture color
    nodes = get_spot(proj_settings.id_data).data.node_tree.nodes['Group'].node_tree.nodes
    c = proj_settings.projected_color
    nodes['Checker Texture'].inputs['Color2'].default_value = [c.r, c.g, c.b, 1]
    eevee.sync(proj_settings.id_data)


def update_power(proj_settings, context):
    # Update spotlight power
    spot = get_spot(proj_settings.id_data)
    spot.data.energy = proj_settings["power"]


def update_pixel_grid(proj_settings, context):
    """ Update the pixel grid. Meaning, make it visible by linking the right node and updating the resolution. """
    root_tree = get_spot(proj_settings.id_data).data.node_tree
    nodes = root_tree.nodes
    pixel_grid_nodes = nodes['pixel_grid'].node_tree.nodes
    width, height = get_resolution(proj_settings, context)
    pixel_grid_nodes['_width'].outputs[0].default_value = width
    pixel_grid_nodes['_height'].outputs[0].default_value = height
    if proj_settings.show_pixel_grid:
        root_tree.links.new(nodes['pixel_grid'].outputs[0], nodes['Light Output'].inputs[0])
    else:
        root_tree.links.new(nodes['Emission'].outputs[0], nodes['Light Output'].inputs[0])

    # Pixelated preview: sample the content once per projector pixel.
    ensure_pixelate_nodes(root_tree)
    nodes['pix_res'].inputs[0].default_value = width
    nodes['pix_res'].inputs[1].default_value = height
    nodes['pix_mix'].inputs[0].default_value = 1.0 if proj_settings.show_pixel_grid else 0.0
    group_nodes = nodes['Group'].node_tree.nodes
    group_nodes['Image Texture'].interpolation = 'Closest' if proj_settings.show_pixel_grid else 'Linear'

    projector = proj_settings.id_data
    if proj_settings.eevee_node_group is not None:
        eevee.ensure_eevee_node_group(projector)   # upgrades older EEVEE setups
    eevee.sync(projector)


def ensure_pixelate_nodes(root_tree):
    """ Insert the pixelate step between the projector coordinates and the custom
    image in the light's node tree (older projectors don't have it). """
    nodes = root_tree.nodes
    if 'pix_mix' in nodes:
        return
    group = nodes['Group']
    image = nodes['Image Texture']
    uv = group.outputs['texture vector']
    x, y = image.location[0] - 900, image.location[1] + 400

    res = nodes.new('ShaderNodeCombineXYZ')
    res.name = res.label = 'pix_res'
    res.inputs[2].default_value = 1.0
    res.location = (x, y - 150)
    mul = nodes.new('ShaderNodeVectorMath')
    mul.operation = 'MULTIPLY'
    mul.location = (x + 180, y)
    flo = nodes.new('ShaderNodeVectorMath')
    flo.operation = 'FLOOR'
    flo.location = (x + 360, y)
    add = nodes.new('ShaderNodeVectorMath')
    add.operation = 'ADD'
    add.inputs[1].default_value = (0.5, 0.5, 0.0)
    add.location = (x + 540, y)
    div = nodes.new('ShaderNodeVectorMath')
    div.operation = 'DIVIDE'
    div.location = (x + 720, y)
    mix = nodes.new('ShaderNodeMix')
    mix.name = mix.label = 'pix_mix'
    mix.data_type = 'VECTOR'
    mix.inputs[0].default_value = 0.0
    mix.location = (x + 900, y)

    links = root_tree.links
    links.new(uv, mul.inputs[0])
    links.new(res.outputs[0], mul.inputs[1])
    links.new(mul.outputs[0], flo.inputs[0])
    links.new(flo.outputs[0], add.inputs[0])
    links.new(add.outputs[0], div.inputs[0])
    links.new(res.outputs[0], div.inputs[1])
    # Mix node: A (index 4) = original, B (index 5) = pixelated, for vectors.
    links.new(uv, mix.inputs[4])
    links.new(div.outputs[0], mix.inputs[5])
    links.new(mix.outputs[1], image.inputs['Vector'])

    
def create_pixel_grid_node_group():
    node_group = bpy.data.node_groups.new(
        '_Projectors-Addon_PixelGrid', 'ShaderNodeTree')

    # Create input/output sockets for the node group.
    if(bpy.app.version >= (4, 0)):
        node_group.interface.new_socket('Shader', socket_type='NodeSocketShader')
        node_group.interface.new_socket('Vector', socket_type='NodeSocketVector')

        node_group.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    else:
        inputs = node_group.inputs
        inputs.new('NodeSocketShader', 'Shader')
        inputs.new('NodeSocketVector', 'Vector')

        outputs = node_group.outputs
        outputs.new('NodeSocketShader', 'Shader')

    nodes = node_group.nodes

    auto_pos = auto_offset()

    group_input = nodes.new('NodeGroupInput')
    group_input.location = auto_pos(200)

    sepXYZ = nodes.new('ShaderNodeSeparateXYZ')
    sepXYZ.location = auto_pos(200)

    in_width = nodes.new('ShaderNodeValue')
    in_width.name = '_width'
    in_width.label = 'Width'
    in_width.location = auto_pos(100)

    in_height = nodes.new('ShaderNodeValue')
    in_height.name = '_height'
    in_height.label = 'Height'
    in_height.location = auto_pos(y=-200)

    mul1 = nodes.new('ShaderNodeMath')
    mul1.operation = 'MULTIPLY'
    mul1.location = auto_pos(100)

    mul2 = nodes.new('ShaderNodeMath')
    mul2.operation = 'MULTIPLY'
    mul2.location = auto_pos(y=-200)

    mod1 = nodes.new('ShaderNodeMath')
    mod1.operation = 'MODULO'
    mod1.inputs[1].default_value = 1
    mod1.location = auto_pos(100)

    mod2 = nodes.new('ShaderNodeMath')
    mod2.operation = 'MODULO'
    mod2.inputs[1].default_value = 1
    mod2.location = auto_pos(y=-200)

    col_ramp1 = nodes.new('ShaderNodeValToRGB')
    col_ramp1.color_ramp.elements[1].position = 0.025
    col_ramp1.color_ramp.interpolation = 'CONSTANT'
    col_ramp1.location = auto_pos(100)

    col_ramp2 = nodes.new('ShaderNodeValToRGB')
    col_ramp2.color_ramp.elements[1].position = 0.025
    col_ramp2.color_ramp.interpolation = 'CONSTANT'
    col_ramp2.location = auto_pos(y=-200)

    mix_rgb = nodes.new('ShaderNodeMixRGB')
    mix_rgb.use_clamp = True
    mix_rgb.blend_type = 'MULTIPLY'
    mix_rgb.inputs[0].default_value = 1
    mix_rgb.location = auto_pos(200)
    
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    transparent.location = auto_pos(y=-200)

    mix_shader = nodes.new('ShaderNodeMixShader')
    mix_shader.location = auto_pos(100)

    group_output = nodes.new('NodeGroupOutput')
    group_output.location = auto_pos(100)
    
    # Link Nodes
    links = node_group.links

    links.new(group_input.outputs[0], mix_shader.inputs[2])
    links.new(group_input.outputs[1], sepXYZ.inputs[0])

    links.new(in_width.outputs[0], mul1.inputs[1])
    links.new(in_height.outputs[0], mul2.inputs[1])

    links.new(sepXYZ.outputs[0], mul1.inputs[0])
    links.new(sepXYZ.outputs[1], mul2.inputs[0])

    links.new(mul1.outputs[0], mod1.inputs[0])
    links.new(mul2.outputs[0], mod2.inputs[0])

    links.new(mod1.outputs[0], col_ramp1.inputs[0])
    links.new(mod2.outputs[0], col_ramp2.inputs[0])

    links.new(col_ramp1.outputs[0], mix_rgb.inputs[1])
    links.new(col_ramp2.outputs[0], mix_rgb.inputs[2])

    links.new(mix_rgb.outputs[0], mix_shader.inputs[0])
    links.new(transparent.outputs[0], mix_shader.inputs[1])

    links.new(mix_shader.outputs[0], group_output.inputs[0])

    return node_group
    

def create_projector(context):
    """
    Create a new projector composed out of a camera (parent obj) and a spotlight (child not intended for user interaction).
    The camera is the object intended for the user to manipulate and custom properties are stored there.
    The spotlight with a custom nodetree is responsible for actual projection of the texture.
    """
    log.debug('Creating projector.')

    # ### Camera ###
    bpy.ops.object.camera_add(enter_editmode=False,
                              location=(0, 0, 0),
                              rotation=(0, 0, 0))
    cam = context.object
    cam.name = 'Projector'
    create_spot(cam)

    # Move newly create projector (cam and spotlight) to 3D-Cursor position.
    cam.location = context.scene.cursor.location
    cam.rotation_euler = context.scene.cursor.rotation_euler
    return cam


def create_spot(cam):
    """ Create the spot light that does the projection and parent it to the camera.
    Uses the data API only, so it also works from handlers and timers. """
    create_projector_textures()
    light = bpy.data.lights.new('Projector.Spot', 'SPOT')
    spot = bpy.data.objects.new('Projector.Spot', light)
    for coll in cam.users_collection:
        coll.objects.link(spot)
    spot.scale = (.01, .01, .01)
    spot.data.spot_size = math.pi - 0.001
    spot.data.spot_blend = 0
    spot.data.shadow_soft_size = 0.0
    spot.hide_select = True
    spot[ADDON_ID.format('spot')] = True
    spot.data.cycles.use_multiple_importance_sampling = False
    # EEVEE ignores the light's node tree; the projection is done in materials instead.
    eevee.mute_spot_in_eevee(spot)
    add_projector_node_tree_to_spot(spot)
    spot.parent = cam
    spot.matrix_parent_inverse.identity()
    return spot


def apply_settings(projector, context=None):
    """ Push the projector's current settings into its node trees, camera and light. """
    ps = projector.proj_settings
    update_throw_ratio(ps, context)
    update_projected_texture(ps, context)
    update_resolution(ps, context)
    update_checker_color(ps, context)
    update_lens_shift(ps, context)
    update_power(ps, context)
    update_pixel_grid(ps, context)


def init_projector(proj_settings, context):
    # # Add custom properties to store projector settings on the camera obj.
    proj_settings.throw_ratio = 0.8
    proj_settings.power = 1000.0
    proj_settings.projected_texture = Textures.CHECKER.value
    proj_settings.h_shift = 0.0
    proj_settings.v_shift = 0.0
    proj_settings.projected_color = random_color()
    proj_settings.resolution = '1920x1080'
    proj_settings.use_custom_texture_res = True

    # Init Projector
    update_throw_ratio(proj_settings, context)
    update_projected_texture(proj_settings, context)
    update_resolution(proj_settings, context)
    update_checker_color(proj_settings, context)
    update_lens_shift(proj_settings, context)
    update_power(proj_settings, context)
    update_pixel_grid(proj_settings, context)


class PROJECTOR_OT_create_projector(Operator):
    """Create Projector"""
    bl_idname = 'projector.create'
    bl_label = 'Create a new Projector'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        projector = create_projector(context)
        init_projector(projector.proj_settings, context)
        duplicate.ensure_uid(projector)
        return {'FINISHED'}


def update_projected_texture(proj_settings, context):
    """ Update the projected output source. """
    projector = proj_settings.id_data
    root_tree = get_spot(projector).data.node_tree
    group_tree = root_tree.nodes['Group'].node_tree
    group_output_node = group_tree.nodes['Group Output']
    group_node = root_tree.nodes['Group']
    emission_node = root_tree.nodes['Emission']

    # Switch between the three possible cases by relinking some nodes.
    case = proj_settings.projected_texture
    if case == Textures.CHECKER.value:
        mix_node = group_tree.nodes['Mix.001']
        group_tree.links.new(
            mix_node.outputs['Color'], group_output_node.inputs[1])
        root_tree.links.new(group_node.outputs[1], emission_node.inputs[0])
    elif case == Textures.COLOR_GRID.value:
        img_node = group_tree.nodes['Image Texture']
        group_tree.links.new(img_node.outputs[0], group_output_node.inputs[1])
        root_tree.links.new(group_node.outputs[1], emission_node.inputs[0])
    elif case == Textures.CUSTOM_TEXTURE.value:
        custom_tex_node = root_tree.nodes['Image Texture']
        root_tree.links.new(
            custom_tex_node.outputs[0], emission_node.inputs[0])
    eevee.sync(projector)


class PROJECTOR_OT_delete_projector(Operator):
    """Delete Projector"""
    bl_idname = 'projector.delete'
    bl_label = 'Delete Projector'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(get_projectors(context, only_selected=True))

    def execute(self, context):
        selected_projectors = get_projectors(context, only_selected=True)
        for projector in selected_projectors:
            eevee.remove_projector(projector)
            for child in projector.children:
                bpy.data.objects.remove(child, do_unlink=True)
            else:
                bpy.data.objects.remove(projector, do_unlink=True)
        return {'FINISHED'}


class PROJECTOR_OT_eevee_add_receivers(Operator):
    """Project onto these objects in EEVEE and Material Preview by adding the projector to their materials (Cycles is not affected)"""
    bl_idname = 'projector.eevee_add_receivers'
    bl_label = 'Add EEVEE Receivers'
    bl_options = {'REGISTER', 'UNDO'}

    all_objects: bpy.props.BoolProperty(
        name="All Objects", default=False,
        description="Use every visible object in the scene instead of only the selected ones")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and get_projector(context) is not None

    def execute(self, context):
        projector = get_projector(context)
        if self.all_objects:
            objects = [o for o in context.scene.objects if o.visible_get()]
        else:
            objects = [o for o in context.selected_objects if o != projector]
        if not objects:
            self.report({'WARNING'}, 'Select the objects to project onto together with the projector')
            return {'CANCELLED'}
        count = eevee.add_receivers(projector, objects)
        self.report({'INFO'}, f'Projector added to {count} material(s)')
        return {'FINISHED'}


class PROJECTOR_OT_eevee_remove_receivers(Operator):
    """Remove this projector from the materials of these objects"""
    bl_idname = 'projector.eevee_remove_receivers'
    bl_label = 'Remove EEVEE Receivers'
    bl_options = {'REGISTER', 'UNDO'}

    all_objects: bpy.props.BoolProperty(
        name="All Objects", default=False,
        description="Remove the projector from every material instead of only those of the selected objects")

    @classmethod
    def poll(cls, context):
        projector = get_projector(context)
        return projector is not None and projector.proj_settings.eevee_node_group is not None

    def execute(self, context):
        projector = get_projector(context)
        objects = None if self.all_objects else [
            o for o in context.selected_objects if o != projector]
        count = eevee.remove_receivers(projector, objects)
        self.report({'INFO'}, f'Projector removed from {count} material(s)')
        return {'FINISHED'}


class PROJECTOR_OT_eevee_bake_shadows(Operator):
    """Bake the EEVEE shadow map of the selected projector (or all projectors with shadows)"""
    bl_idname = 'projector.eevee_bake_shadows'
    bl_label = 'Bake Projector Shadows'
    bl_options = {'REGISTER', 'UNDO'}

    all_projectors: bpy.props.BoolProperty(name="All Projectors", default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if self.all_projectors:
            projectors = [p for p in get_projectors(context)
                          if p.proj_settings.eevee_node_group is not None and p.proj_settings.eevee_shadows]
        else:
            p = get_projector(context)
            projectors = [p] if p is not None and p.proj_settings.eevee_node_group is not None else []
        if not projectors:
            self.report({'WARNING'}, 'No projector with EEVEE receivers selected')
            return {'CANCELLED'}
        for p in projectors:
            eevee.ensure_eevee_node_group(p)
        shadows.bake_all(projectors, context.evaluated_depsgraph_get())
        t = sum(p.proj_settings.shadow_bake_time for p in projectors)
        self.report({'INFO'}, f'Baked {len(projectors)} shadow map(s) in {t:.2f}s')
        return {'FINISHED'}


class PROJECTOR_OT_duplicate_projector(Operator):
    """Duplicate the selected projector, with its settings, body and EEVEE receivers. Shift+D works too"""
    bl_idname = 'projector.duplicate'
    bl_label = 'Duplicate Projector'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and get_projector(context) is not None

    def execute(self, context):
        source = get_projector(context)
        new = duplicate.duplicate(source)
        for obj in context.selected_objects:
            obj.select_set(False)
        new.select_set(True)
        context.view_layer.objects.active = new
        return {'FINISHED'}


class PROJECTOR_OT_reinit_projector(Operator):
    """Rebuild the selected projectors from their settings, if something broke. Keeps the custom image, body and EEVEE receivers"""
    bl_idname = 'projector.reinit'
    bl_label = 'Reinitialize Projector'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(get_projectors(context, only_selected=True))

    def execute(self, context):
        projectors = get_projectors(context, only_selected=True)
        for p in projectors:
            duplicate.reinit(p)
        self.report({'INFO'}, f'Reinitialized {len(projectors)} projector(s)')
        return {'FINISHED'}


class ProjectorReceiver(bpy.types.PropertyGroup):
    material: bpy.props.PointerProperty(type=bpy.types.Material)


class PROJECTOR_OT_measure_distance(Operator):
    """Measure the throw distance: from the lens along its axis to the first surface it hits"""
    bl_idname = 'projector.measure_distance'
    bl_label = 'Measure Throw Distance'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def execute(self, context):
        projector = get_projector(context)
        spot = get_spot(projector)
        mw = (spot or projector).matrix_world
        origin = mw.translation
        direction = (mw.to_3x3().normalized() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
        depsgraph = context.evaluated_depsgraph_get()
        hit, loc, _n, _i, obj, _m = context.scene.ray_cast(depsgraph, origin, direction)
        if not hit:
            self.report({'WARNING'}, 'Nothing in front of the projector')
            return {'CANCELLED'}
        projector.proj_settings.plan_distance = (loc - origin).length
        self.report({'INFO'}, f'{obj.name}: {(loc - origin).length:.3f} m')
        return {'FINISHED'}


class ProjectorSettings(bpy.types.PropertyGroup):
    throw_ratio: bpy.props.FloatProperty(
        name="Throw Ratio",
        soft_min=0.2, soft_max=10,
        update=update_throw_ratio,
        subtype='FACTOR')
    power: bpy.props.FloatProperty(
        name="Projector Power",
        soft_min=0, soft_max=999999,
        update=update_power,
        unit='POWER')
    resolution: bpy.props.EnumProperty(
        items=RESOLUTIONS,
        default='1920x1080',
        description="Select a Resolution for your Projector",
        update=update_resolution)
    use_custom_texture_res: bpy.props.BoolProperty(
        name="Let Image Define Projector Resolution",
        default=True,
        description="Use the resolution from the image as the projector resolution. Warning: After selecting a new image toggle this checkbox to update",
        update=update_throw_ratio)
    h_shift: bpy.props.FloatProperty(
        name="Horizontal Shift",
        description="Horizontal Lens Shift",
        soft_min=-150, soft_max=150,
        update=update_lens_shift,
        subtype='PERCENTAGE')
    v_shift: bpy.props.FloatProperty(
        name="Vertical Shift",
        description="Vertical Lens Shift",
        soft_min=-150, soft_max=150,
        update=update_lens_shift,
        subtype='PERCENTAGE')
    projected_color: bpy.props.FloatVectorProperty(
        subtype='COLOR',
        update=update_checker_color)
    projected_texture: bpy.props.EnumProperty(
        items=PROJECTED_OUTPUTS,
        default=Textures.CHECKER.value,
        description="What do you to project?",
        update=update_throw_ratio)
    show_pixel_grid: bpy.props.BoolProperty(
        name="Show Pixel Grid",
        description="When checked the image is divided into a pixel grid with the dimensions of the image resolution.",
        default=False,
        update=update_pixel_grid)
    custom_resolution: bpy.props.IntVectorProperty(
        name="Custom Resolution",
        description="Width and height in pixels, used when Resolution is Custom",
        size=2, default=(1920, 1080), min=1, soft_max=8192,
        update=update_resolution)

    # Preset (model + lens)
    preset_id: bpy.props.StringProperty()
    preset_name: bpy.props.StringProperty(name="Model")
    preset_lens: bpy.props.StringProperty(name="Lens")
    lumens: bpy.props.FloatProperty(
        name="Brightness",
        description="Brightness of the projector in lumens. For information only: it doesn't change Power",
        default=0.0, min=0.0, soft_max=60000, step=10000, precision=0)

    show_preset_notes: bpy.props.BoolProperty(
        name="Show Notes", description="Show the notes of this model and lens", default=False)

    # Lens limits
    limit_throw: bpy.props.BoolProperty(
        name="Limit Throw Ratio",
        description="Keep the throw ratio inside the lens' zoom range",
        default=False, update=update_limits)
    throw_limits: bpy.props.FloatVectorProperty(
        name="Throw Ratio Range",
        description="Shortest and longest throw ratio of the lens (equal for a fixed lens)",
        size=2, default=(0.8, 2.0), min=0.01, soft_max=15.0, precision=3,
        update=update_limits)
    zoom: bpy.props.FloatProperty(
        name="Zoom",
        description="Position on the lens' zoom range: 0% is wide (shortest throw, biggest image), 100% is tele",
        subtype='PERCENTAGE', min=0.0, max=100.0,
        get=get_zoom, set=set_zoom)
    limit_shift: bpy.props.BoolProperty(
        name="Limit Lens Shift",
        description="Keep the lens shift inside the lens' range",
        default=False, update=update_lens_shift)
    v_shift_limits: bpy.props.FloatVectorProperty(
        name="Vertical Shift Range",
        description="Lowest and highest vertical lens shift (% of image height from centred)",
        size=2, default=(-50.0, 50.0), soft_min=-150, soft_max=150,
        update=update_lens_shift)
    h_shift_limits: bpy.props.FloatVectorProperty(
        name="Horizontal Shift Range",
        description="Lowest and highest horizontal lens shift (% of image width from centred)",
        size=2, default=(-20.0, 20.0), soft_min=-150, soft_max=150,
        update=update_lens_shift)

    # Image size calculator
    plan_distance: bpy.props.FloatProperty(
        name="Throw Distance",
        description="Distance from the lens to the surface, along the lens axis. Use Measure to get it from the scene",
        default=3.0, min=0.01, soft_max=30.0, subtype='DISTANCE', unit='LENGTH')
    plan_solve: bpy.props.EnumProperty(
        name="When Changing the Image Size",
        description="What to adjust when you type an image size",
        items=[('THROW', 'Adjust Throw Ratio', 'Keep the distance, change the zoom'),
               ('DISTANCE', 'Adjust Distance', 'Keep the zoom, change the distance')],
        default='THROW')
    image_width: bpy.props.FloatProperty(
        name="Image Width", subtype='DISTANCE', unit='LENGTH', min=0.0, soft_max=20.0,
        description="Width of the image at the throw distance",
        get=get_image_width, set=set_image_width)
    image_height: bpy.props.FloatProperty(
        name="Image Height", subtype='DISTANCE', unit='LENGTH', min=0.0, soft_max=20.0,
        description="Height of the image at the throw distance",
        get=get_image_height, set=set_image_height)
    image_diagonal: bpy.props.FloatProperty(
        name="Image Diagonal", subtype='DISTANCE', unit='LENGTH', min=0.0, soft_max=25.0,
        description="Diagonal of the image at the throw distance",
        get=get_image_diagonal, set=set_image_diagonal)

    show_body: bpy.props.BoolProperty(
        name="Show Body",
        description="Add a box for the projector housing behind the lens. It renders and blocks other projectors' beams",
        default=False,
        update=body.update_show_body)
    body_size: bpy.props.FloatVectorProperty(
        name="Body Size",
        description="Width, height and depth of the projector housing",
        size=3, default=(0.5, 0.2, 0.45), min=0.001, soft_max=2.0,
        subtype='XYZ_LENGTH', unit='LENGTH',
        update=body.update_body_size)
    body_lens_offset: bpy.props.FloatVectorProperty(
        name="Lens Offset",
        description="Where the lens sits on the front of the housing, measured from its centre (right, up)",
        size=2, default=(0.0, 0.0), soft_min=-1.0, soft_max=1.0,
        subtype='TRANSLATION', unit='LENGTH',
        update=body.update_body_size)
    eevee_shadows: bpy.props.BoolProperty(
        name="Shadows",
        description="Let objects block the projection in EEVEE, using a shadow map baked from the projector",
        default=False,
        update=update_eevee_shadows)
    shadow_resolution: bpy.props.EnumProperty(
        name="Shadow Resolution",
        description="Size of the longest side of the baked shadow map. Higher is sharper but slower to bake",
        items=[('256', '256', ''), ('512', '512', ''), ('1024', '1024', ''), ('2048', '2048', '')],
        default='1024',
        update=update_shadow_resolution)
    shadow_bias: bpy.props.FloatProperty(
        name="Shadow Bias",
        description="Raise this if surfaces facing away at steep angles show speckled self-shadowing; lower it if shadows detach from objects",
        default=0.02, min=0.0, soft_max=0.1, subtype='FACTOR',
        update=update_shadow_bias)
    shadow_auto_update: bpy.props.BoolProperty(
        name="Auto Update",
        description="Re-bake the shadow map shortly after objects stop moving in the viewport",
        default=True)
    shadow_image: bpy.props.PointerProperty(type=bpy.types.Image)
    shadow_bake_time: bpy.props.FloatProperty(default=0.0)
    receivers: bpy.props.CollectionProperty(
        type=ProjectorReceiver,
        description="Materials this projector projects onto in EEVEE (kept so Reinit can restore them)")
    custom_image: bpy.props.PointerProperty(
        type=bpy.types.Image,
        description="Backup of the custom image, so Reinit can restore it")
    projector_uid: bpy.props.StringProperty(
        description="Internal id, used to find the original when a projector is copied")
    eevee_node_group: bpy.props.PointerProperty(
        name="EEVEE Node Group",
        description="Material node group that does this projector's projection in EEVEE",
        type=bpy.types.NodeTree)


def register():
    bpy.utils.register_class(ProjectorReceiver)
    bpy.utils.register_class(ProjectorSettings)
    bpy.utils.register_class(PROJECTOR_OT_create_projector)
    bpy.utils.register_class(PROJECTOR_OT_delete_projector)
    bpy.utils.register_class(PROJECTOR_OT_change_color_randomly)
    bpy.utils.register_class(PROJECTOR_OT_eevee_add_receivers)
    bpy.utils.register_class(PROJECTOR_OT_eevee_remove_receivers)
    bpy.utils.register_class(PROJECTOR_OT_eevee_bake_shadows)
    bpy.utils.register_class(PROJECTOR_OT_duplicate_projector)
    bpy.utils.register_class(PROJECTOR_OT_reinit_projector)
    bpy.utils.register_class(PROJECTOR_OT_measure_distance)
    presets.register()
    bpy.types.Object.proj_settings = bpy.props.PointerProperty(
        type=ProjectorSettings)
    eevee.register()


def unregister():
    eevee.unregister()
    duplicate.unregister()
    cleanup.unregister()
    body.unregister()
    presets.unregister()
    bpy.utils.unregister_class(PROJECTOR_OT_measure_distance)
    bpy.utils.unregister_class(PROJECTOR_OT_reinit_projector)
    bpy.utils.unregister_class(PROJECTOR_OT_duplicate_projector)
    bpy.utils.unregister_class(PROJECTOR_OT_eevee_bake_shadows)
    bpy.utils.unregister_class(PROJECTOR_OT_eevee_remove_receivers)
    bpy.utils.unregister_class(PROJECTOR_OT_eevee_add_receivers)
    bpy.utils.unregister_class(PROJECTOR_OT_change_color_randomly)
    bpy.utils.unregister_class(PROJECTOR_OT_delete_projector)
    bpy.utils.unregister_class(PROJECTOR_OT_create_projector)
    bpy.utils.unregister_class(ProjectorSettings)
    bpy.utils.unregister_class(ProjectorReceiver)
