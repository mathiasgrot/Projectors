import logging
import math
import os

from enum import Enum
import bpy
from bpy.types import Operator

from .helper import (ADDON_ID, auto_offset,
                     get_projectors, get_projector, get_spot, random_color)
from . import eevee, shadows, body, duplicate, cleanup

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
    ('1000x1000', 'Square (1000x1000) 1:1', '', 12)
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
    name_template = '_proj.tex.{}'
    for res in RESOLUTIONS:
        img_name = name_template.format(res[0])
        w, h = res[0].split('x')
        if not bpy.data.images.get(img_name):
            log.debug(f'Create projection texture: {res}')
            img = bpy.data.images.new(img_name, int(w), int(h), alpha=True)
            img.generated_type = 'COLOR_GRID'

        bpy.data.images[img_name].use_fake_user = True


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
    w, h = settings.resolution.split('x')
    return float(w), float(h)


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
    # Update properties of the camera.
    throw_ratio = proj_settings.get('throw_ratio')
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
    h_shift = proj_settings.get('h_shift', 0.0) / 100
    v_shift = proj_settings.get('v_shift', 0.0) / 100
    throw_ratio = proj_settings.get('throw_ratio')

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
    nodes['Image Texture'].image = bpy.data.images[f'_proj.tex.{proj_settings.resolution}']
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
    eevee.sync(proj_settings.id_data)

    
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


class ProjectorSettings(bpy.types.PropertyGroup):
    throw_ratio: bpy.props.FloatProperty(
        name="Throw Ratio",
        soft_min=0.4, soft_max=3,
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
        soft_min=-20, soft_max=20,
        update=update_lens_shift,
        subtype='PERCENTAGE')
    v_shift: bpy.props.FloatProperty(
        name="Vertical Shift",
        description="Vertical Lens Shift",
        soft_min=-20, soft_max=20,
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
    bpy.types.Object.proj_settings = bpy.props.PointerProperty(
        type=ProjectorSettings)
    eevee.register()


def unregister():
    eevee.unregister()
    duplicate.unregister()
    cleanup.unregister()
    body.unregister()
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
