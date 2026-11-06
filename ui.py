from .helper import get_projectors, get_spot
from .projector import RESOLUTIONS, Textures
from . import eevee, presets
import textwrap


def _wrapped(layout, text, width=42, icon='NONE'):
    col = layout.column(align=True)
    for i, line in enumerate(textwrap.wrap(text, width)):
        col.label(text=line, icon=icon if i == 0 else 'BLANK1')

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

            ps = proj_settings
            # Model and lens
            layout.label(text='Model:')
            box = layout.box()
            col = box.column(align=True)
            col.menu('PROJECTOR_MT_models', text=ps.preset_name or 'Choose a Model…', icon='PRESET')
            preset = presets.current_preset(projector) if ps.preset_id else None
            if ps.preset_id and preset is None:
                box.label(text='Preset file not found', icon='ERROR')
            if preset and preset.get('lenses'):
                col.menu('PROJECTOR_MT_lenses', text=ps.preset_lens or 'Choose a Lens…', icon='CAMERA_DATA')
            if preset:
                if ps.lumens > 0:
                    note = preset.get('lumens_note')
                    box.label(text=f'{ps.lumens:,.0f} lm' + (f'  ({note})' if note else ''), icon='LIGHT_SUN')
                lens = presets.current_lens(projector)
                if lens and lens.get('note'):
                    _wrapped(box, lens['note'], icon='INFO')
                if preset.get('note'):
                    _wrapped(box, preset['note'], icon='INFO')

            layout.label(text='Projector Settings:')
            box = layout.box()
            col = box.column(align=True)
            col.prop(ps, 'throw_ratio')
            if ps.limit_throw:
                lo, hi = sorted(ps.throw_limits)
                col.label(text=f'Lens range {lo:g} – {hi:g}:1' if lo != hi else f'Fixed lens {lo:g}:1',
                          icon='LOCKED')
            box.prop(ps, 'power', text='Power')
            res_col = box.column(align=True)
            res_col.prop(ps, 'resolution', text='Resolution', icon='PRESET')
            if ps.resolution == 'custom':
                res_col.prop(ps, 'custom_resolution', index=0, text='Width')
                res_col.prop(ps, 'custom_resolution', index=1, text='Height')
            if ps.projected_texture == Textures.CUSTOM_TEXTURE.value and ps.use_custom_texture_res:
                res_col.enabled = False
            # Lens Shift
            col = box.column(align=True)
            col.prop(ps, 'h_shift', text='Horizontal Shift')
            col.prop(ps, 'v_shift', text='Vertical Shift')
            if ps.limit_shift:
                hl, hh = sorted(ps.h_shift_limits)
                vl, vh = sorted(ps.v_shift_limits)
                col.label(text=f'Lens range H {hl:g} to {hh:g}%, V {vl:g} to {vh:g}%', icon='LOCKED')
            # Lens limits (filled in by the lens preset, editable)
            sub = box.column(heading='Lens Limits', align=True)
            sub.prop(ps, 'limit_throw', text='Throw Ratio')
            if ps.limit_throw:
                row = sub.row(align=True)
                row.prop(ps, 'throw_limits', index=0, text='Min')
                row.prop(ps, 'throw_limits', index=1, text='Max')
            sub.prop(ps, 'limit_shift', text='Lens Shift')
            if ps.limit_shift:
                row = sub.row(align=True)
                row.prop(ps, 'h_shift_limits', index=0, text='H Min')
                row.prop(ps, 'h_shift_limits', index=1, text='Max')
                row = sub.row(align=True)
                row.prop(ps, 'v_shift_limits', index=0, text='V Min')
                row.prop(ps, 'v_shift_limits', index=1, text='Max')
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
            # Pixel Grid
            box.prop(proj_settings, 'show_pixel_grid', text='Pixel Grid & Pixelated Preview')

            # Image size calculator
            layout.label(text='Image Size:')
            box = layout.box()
            row = box.row(align=True)
            row.prop(ps, 'plan_distance', text='Throw Distance')
            row.operator('projector.measure_distance', text='', icon='DRIVER_DISTANCE')
            box.row().prop(ps, 'plan_solve', expand=True)
            col = box.column(align=True)
            col.prop(ps, 'image_width', text='Width')
            col.prop(ps, 'image_height', text='Height')
            col.prop(ps, 'image_diagonal', text='Diagonal')
            from .projector import get_resolution_for
            rw, rh = get_resolution_for(projector)
            px_mm = ps.image_width / rw * 1000 if rw else 0
            box.label(text=f'1 pixel ≈ {px_mm:.2f} mm', icon='TEXTURE')
            if ps.limit_throw:
                lo, hi = sorted(ps.throw_limits)
                w = ps.image_width
                if lo != hi:
                    box.label(text=f'This lens gives {w:.2f} m width from {lo * w:.2f} to {hi * w:.2f} m',
                              icon='ARROW_LEFTRIGHT')
                else:
                    box.label(text=f'This lens gives {w:.2f} m width at {lo * w:.2f} m', icon='ARROW_LEFTRIGHT')
                # In THROW mode a width outside the zoom range gets clamped: say so.
                if ps.plan_solve == 'THROW':
                    wmin, wmax = ps.plan_distance / hi, ps.plan_distance / lo
                    box.label(text=f'At {ps.plan_distance:.2f} m: {wmin:.2f} – {wmax:.2f} m wide',
                              icon='INFO')

            layout.prop(proj_settings,
                        'projected_texture', text='Project')

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
