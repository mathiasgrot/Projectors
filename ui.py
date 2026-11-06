from .helper import get_projectors, get_spot
from .projector import RESOLUTIONS, Textures
from . import eevee

import bpy
from bpy.types import Panel, PropertyGroup, UIList, Operator


class PROJECTOR_PT_projector_settings(Panel):
    bl_idname = 'OBJECT_PT_projector_n_panel'
    bl_label = 'Projector'
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Projector"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator('projector.create',
                     icon='ADD', text="New")
        row.operator('projector.delete',
                     text='Remove', icon='REMOVE')
        row = col.row(align=True)
        row.operator('projector.duplicate',
                     text='Duplicate', icon='DUPLICATE')
        row.operator('projector.reinit',
                     text='Reinit', icon='FILE_REFRESH')

        selected_projectors = get_projectors(context, only_selected=True)
        if len(selected_projectors) == 1:
            projector = selected_projectors[0]
            proj_settings = projector.proj_settings

            layout.separator()

            layout.label(text='Projector Settings:')
            box = layout.box()
            box.prop(proj_settings, 'throw_ratio')
            box.prop(proj_settings, 'power', text='Power')
            res_row = box.row()
            res_row.prop(proj_settings, 'resolution',
                         text='Resolution', icon='PRESET')
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value and proj_settings.use_custom_texture_res:
                res_row.active = False
                res_row.enabled = False
            else:
                res_row.active = True
                res_row.enabled = True
            # Lens Shift
            col = box.column(align=True)
            col.prop(proj_settings,
                     'h_shift', text='Horizontal Shift')
            col.prop(proj_settings, 'v_shift', text='Vertical Shift')
            # Body
            box.prop(proj_settings, 'show_body')
            if proj_settings.show_body:
                col = box.column(align=True)
                col.prop(proj_settings, 'body_size', index=0, text='Width')
                col.prop(proj_settings, 'body_size', index=1, text='Height')
                col.prop(proj_settings, 'body_size', index=2, text='Depth')
                col = box.column(align=True)
                col.prop(proj_settings, 'body_lens_offset', index=0, text='Lens Offset X')
                col.prop(proj_settings, 'body_lens_offset', index=1, text='Y')
            layout.prop(proj_settings,
                        'projected_texture', text='Project')
            # Pixel Grid
            box.prop(proj_settings, 'show_pixel_grid')

            # Custom Texture
            if proj_settings.projected_texture == Textures.CUSTOM_TEXTURE.value:
                box = layout.box()
                box.prop(proj_settings, 'use_custom_texture_res')
                node = get_spot(projector).data.node_tree.nodes['Image Texture']
                box.template_image(node, 'image', node.image_user, compact=False)

            # EEVEE / Material Preview
            layout.separator()
            layout.label(text='EEVEE & Material Preview:')
            box = layout.box()
            count = eevee.receiver_count(projector)
            if count:
                box.label(text=f'Projecting onto {count} material(s)', icon='CHECKMARK')
            else:
                if eevee.is_eevee(context):
                    box.label(text='Add receivers to see the projection.', icon='INFO')
                else:
                    box.label(text='Add receivers to see it in EEVEE.', icon='INFO')
            col = box.column(align=True)
            row = col.row(align=True)
            op = row.operator('projector.eevee_add_receivers', text='Add Selected', icon='ADD')
            op.all_objects = False
            op = row.operator('projector.eevee_add_receivers', text='Add All', icon='WORLD')
            op.all_objects = True
            row = col.row(align=True)
            op = row.operator('projector.eevee_remove_receivers', text='Remove Selected', icon='REMOVE')
            op.all_objects = False
            op = row.operator('projector.eevee_remove_receivers', text='Remove All', icon='X')
            op.all_objects = True
            if count:
                settings = projector.proj_settings
                sbox = box.box()
                sbox.prop(settings, 'eevee_shadows')
                if settings.eevee_shadows:
                    col = sbox.column()
                    col.prop(settings, 'shadow_resolution', text='Resolution')
                    col.prop(settings, 'shadow_bias', text='Bias')
                    col.prop(settings, 'shadow_auto_update')
                    row = col.row()
                    row.operator('projector.eevee_bake_shadows', text='Bake Now', icon='FILE_REFRESH')
                    if settings.shadow_image is not None:
                        col.label(text=f'Last bake: {settings.shadow_bake_time:.2f}s', icon='TIME')
                    if settings.shadow_auto_update:
                        col.label(text='Re-bakes after things stop moving. Animations use the last bake.', icon='INFO')


class PROJECTOR_PT_projected_color(Panel):
    bl_label = "Projected Color"
    bl_parent_id = "OBJECT_PT_projector_n_panel"
    bl_option = {'DEFAULT_CLOSED'}
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    @classmethod
    def poll(self, context):
        """ Only show if projected texture is set to  'checker'."""
        projector = context.object
        return bool(get_projectors(context, only_selected=True)) and projector.proj_settings.projected_texture == Textures.CHECKER.value

    def draw(self, context):
        projector = context.object
        layout = self.layout
        layout.use_property_decorate = False
        col = layout.column()
        col.use_property_split = True
        col.prop(projector.proj_settings, 'projected_color', text='Color')
        col.operator('projector.change_color',
                     icon='MODIFIER_ON', text='Random Color')


def append_to_add_menu(self, context):
    self.layout.operator('projector.create',
                         text='Projector', icon='CAMERA_DATA')


def register():
    bpy.utils.register_class(PROJECTOR_PT_projector_settings)
    bpy.utils.register_class(PROJECTOR_PT_projected_color)
    # Register create  in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.append(append_to_add_menu)


def unregister():
    # Register create in the blender add menu.
    bpy.types.VIEW3D_MT_light_add.remove(append_to_add_menu)
    bpy.utils.unregister_class(PROJECTOR_PT_projected_color)
    bpy.utils.unregister_class(PROJECTOR_PT_projector_settings)
