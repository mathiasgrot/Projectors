"""
Projector presets: real projector models with their lenses.

A preset is a JSON file describing one projector model (body) and the lenses
that fit it. The throw ratio range belongs to the lens, not the projector, so
picking a model and then a lens sets:

* model: resolution, brightness (lumens, for information), housing size
* lens:  throw ratio range and lens shift range (as limits on the sliders)

Loading a preset never touches what is projected (texture, image, colour).

Built-in presets ship in the addon's ``presets`` folder. Your own presets are
saved to Blender's user folder for the addon, so updating the addon doesn't
wipe them. Preset JSON format::

    {
      "name": "Panasonic PT-RQ35K",
      "lumens": 30000,                      # optional
      "resolution": [3840, 2400],
      "body": {"width": 0.598, "height": 0.353, "depth": 0.780},   # optional, metres
      "lens_offset": [0.0, 0.0],            # optional, metres
      "lenses": [
        {"name": "ET-D3LEW200", "throw": [0.645, 0.85],
         "v_shift": [-48, 48], "h_shift": [-15, 15],   # optional, % like the addon
         "note": "..."}                                 # optional
      ],
      "note": "...", "sources": ["https://..."]         # optional
    }

Lens shift uses this addon's convention: percent of image height (vertical)
or width (horizontal), measured from the centred position.
"""

import json
import os
import re

import bpy
from bpy.types import Menu, Operator

from .helper import get_projector

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'presets')


def user_dir(create=False):
    """ Folder for the user's own presets, outside the addon folder. """
    package = __package__ or 'projectors'
    try:
        # Installed as an extension (Blender 4.2+).
        return bpy.utils.extension_path_user(package, path='presets', create=create)
    except (ValueError, AttributeError, TypeError):
        path = bpy.utils.user_resource('SCRIPTS', path=os.path.join('presets', 'projectors'), create=create)
        return path


def _read_dir(folder, source):
    out = []
    if not folder or not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith('.json'):
            continue
        path = os.path.join(folder, fn)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data.get('name'):
                continue
            data['_id'] = f'{source}:{fn}'
            data['_source'] = source
            data['_path'] = path
            out.append(data)
        except (OSError, ValueError) as e:
            print(f'[Projectors Addon]: could not read preset {path}: {e}')
    return out


_cache = {'key': None, 'data': []}


def _dir_key(folder):
    if not folder or not os.path.isdir(folder):
        return None
    return tuple(sorted((fn, os.path.getmtime(os.path.join(folder, fn)))
                        for fn in os.listdir(folder) if fn.lower().endswith('.json')))


def load_all():
    """ All presets, built-in first. Re-read only when the files change. """
    udir = user_dir()
    key = (_dir_key(BUILTIN_DIR), udir, _dir_key(udir))
    if key != _cache['key']:
        _cache['data'] = _read_dir(BUILTIN_DIR, 'builtin') + _read_dir(udir, 'user')
        _cache['key'] = key
    return _cache['data']


def find(preset_id):
    for p in load_all():
        if p['_id'] == preset_id:
            return p
    return None


def current_preset(projector):
    pid = projector.proj_settings.preset_id
    return find(pid) if pid else None


def current_lens(projector):
    preset = current_preset(projector)
    if preset is None:
        return None
    name = projector.proj_settings.preset_lens
    for lens in preset.get('lenses', []):
        if lens.get('name') == name:
            return lens
    return None


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def _set_resolution(ps, w, h):
    from .projector import RESOLUTIONS
    ident = f'{int(w)}x{int(h)}'
    if any(item[0] == ident for item in RESOLUTIONS):
        ps.resolution = ident
    else:
        ps.custom_resolution = (int(w), int(h))
        ps.resolution = 'custom'


def apply_model(projector, preset):
    ps = projector.proj_settings
    ps.preset_id = preset['_id']
    ps.preset_name = preset['name']
    ps.lumens = float(preset.get('lumens') or 0.0)

    res = preset.get('resolution')
    if res and len(res) == 2:
        # The preset's resolution only matters if the content doesn't define it.
        _set_resolution(ps, res[0], res[1])

    body = preset.get('body')
    if body:
        ps.body_size = (float(body['width']), float(body['height']), float(body['depth']))
        offset = preset.get('lens_offset') or (0.0, 0.0)
        ps.body_lens_offset = (float(offset[0]), float(offset[1]))
        ps.show_body = True

    lenses = preset.get('lenses') or []
    keep = next((l for l in lenses if l.get('name') == ps.preset_lens), None)
    lens = keep or (lenses[0] if lenses else None)
    if lens is not None:
        apply_lens(projector, lens)
    else:
        ps.preset_lens = ''
        ps.limit_throw = False
        ps.limit_shift = False


def apply_lens(projector, lens):
    ps = projector.proj_settings
    ps.preset_lens = lens.get('name', '')
    throw = lens.get('throw')
    if throw:
        lo, hi = float(min(throw)), float(max(throw))
        ps.throw_limits = (lo, hi)
        ps.limit_throw = True   # clamps the current throw ratio into range
    else:
        ps.limit_throw = False

    v, h = lens.get('v_shift'), lens.get('h_shift')
    if v or h:
        v = v or (-100.0, 100.0)
        h = h or (-100.0, 100.0)
        ps.v_shift_limits = (float(min(v)), float(max(v)))
        ps.h_shift_limits = (float(min(h)), float(max(h)))
        ps.limit_shift = True
    else:
        ps.limit_shift = False


def clear_preset(projector):
    ps = projector.proj_settings
    ps.preset_id = ''
    ps.preset_name = ''
    ps.preset_lens = ''
    ps.lumens = 0.0
    ps.limit_throw = False
    ps.limit_shift = False


def preset_from_projector(projector, name):
    """ Build a preset dict from the projector's current setup. """
    from .projector import get_resolution_for
    ps = projector.proj_settings
    w, h = get_resolution_for(projector)
    data = {'name': name, 'resolution': [int(w), int(h)]}
    if ps.lumens > 0:
        data['lumens'] = round(ps.lumens)
    if ps.show_body:
        bw, bh, bd = ps.body_size
        data['body'] = {'width': round(bw, 4), 'height': round(bh, 4), 'depth': round(bd, 4)}
        ox, oy = ps.body_lens_offset
        if ox or oy:
            data['lens_offset'] = [round(ox, 4), round(oy, 4)]
    if ps.limit_throw:
        throw = [round(ps.throw_limits[0], 4), round(ps.throw_limits[1], 4)]
    else:
        throw = [round(ps.throw_ratio, 4), round(ps.throw_ratio, 4)]
    lens = {'name': ps.preset_lens or 'Lens', 'throw': throw}
    if ps.limit_shift:
        lens['v_shift'] = [round(x, 2) for x in ps.v_shift_limits]
        lens['h_shift'] = [round(x, 2) for x in ps.h_shift_limits]
    data['lenses'] = [lens]
    return data


def save_user_preset(data):
    folder = user_dir(create=True)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', data['name']).strip('_').lower() or 'preset'
    path = os.path.join(folder, f'{safe}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path, f'user:{safe}.json'


# ---------------------------------------------------------------------------
# UI: menus and operators
# ---------------------------------------------------------------------------

class PROJECTOR_MT_models(Menu):
    bl_idname = 'PROJECTOR_MT_models'
    bl_label = 'Projector Model'

    def draw(self, context):
        layout = self.layout
        presets = load_all()
        builtin = [p for p in presets if p['_source'] == 'builtin']
        user = [p for p in presets if p['_source'] == 'user']
        for p in builtin:
            op = layout.operator('projector.apply_model', text=p['name'])
            op.preset_id = p['_id']
        if user:
            layout.separator()
            layout.label(text='Your presets')
            for p in user:
                op = layout.operator('projector.apply_model', text=p['name'], icon='USER')
                op.preset_id = p['_id']
        layout.separator()
        layout.operator('projector.clear_model', text='None (no limits)', icon='X')
        layout.operator('projector.save_preset', text='Save Current as Preset…', icon='FILE_NEW')
        layout.operator('projector.open_presets_folder', text='Open My Presets Folder', icon='FILE_FOLDER')


class PROJECTOR_MT_lenses(Menu):
    bl_idname = 'PROJECTOR_MT_lenses'
    bl_label = 'Lens'

    def draw(self, context):
        layout = self.layout
        projector = get_projector(context)
        preset = current_preset(projector) if projector else None
        if preset is None:
            layout.label(text='Pick a model first')
            return
        for i, lens in enumerate(preset.get('lenses', [])):
            t = lens.get('throw') or [0, 0]
            label = f"{lens.get('name', 'Lens')}   ({min(t):g}–{max(t):g}:1)" if t[0] != t[1] \
                else f"{lens.get('name', 'Lens')}   ({t[0]:g}:1)"
            op = layout.operator('projector.apply_lens', text=label)
            op.index = i


class PROJECTOR_OT_apply_model(Operator):
    """Use this projector model: resolution, housing size and its lenses"""
    bl_idname = 'projector.apply_model'
    bl_label = 'Apply Projector Model'
    bl_options = {'REGISTER', 'UNDO'}

    preset_id: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def execute(self, context):
        preset = find(self.preset_id)
        if preset is None:
            self.report({'ERROR'}, 'Preset not found')
            return {'CANCELLED'}
        apply_model(get_projector(context), preset)
        return {'FINISHED'}


class PROJECTOR_OT_apply_lens(Operator):
    """Use this lens: limits the throw ratio and lens shift to what it can do"""
    bl_idname = 'projector.apply_lens'
    bl_label = 'Apply Lens'
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def execute(self, context):
        projector = get_projector(context)
        preset = current_preset(projector)
        lenses = preset.get('lenses', []) if preset else []
        if not 0 <= self.index < len(lenses):
            return {'CANCELLED'}
        apply_lens(projector, lenses[self.index])
        return {'FINISHED'}


class PROJECTOR_OT_clear_model(Operator):
    """Don't use a projector model: remove the lens limits"""
    bl_idname = 'projector.clear_model'
    bl_label = 'Clear Projector Model'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def execute(self, context):
        clear_preset(get_projector(context))
        return {'FINISHED'}


class PROJECTOR_OT_save_preset(Operator):
    """Save this projector's resolution, housing, brightness and lens limits as your own preset"""
    bl_idname = 'projector.save_preset'
    bl_label = 'Save Projector Preset'

    name: bpy.props.StringProperty(name='Name', default='My Projector')

    @classmethod
    def poll(cls, context):
        return get_projector(context) is not None

    def invoke(self, context, event):
        ps = get_projector(context).proj_settings
        if ps.preset_name:
            self.name = ps.preset_name + ' (custom)'
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not self.name.strip():
            self.report({'ERROR'}, 'Give the preset a name')
            return {'CANCELLED'}
        projector = get_projector(context)
        data = preset_from_projector(projector, self.name.strip())
        try:
            path, preset_id = save_user_preset(data)
        except OSError as e:
            self.report({'ERROR'}, f'Could not save preset: {e}')
            return {'CANCELLED'}
        ps = projector.proj_settings
        ps.preset_id = preset_id
        ps.preset_name = data['name']
        ps.preset_lens = data['lenses'][0]['name']
        self.report({'INFO'}, f'Saved {os.path.basename(path)}')
        return {'FINISHED'}


class PROJECTOR_OT_open_presets_folder(Operator):
    """Open the folder with your own presets, to edit, share or delete them"""
    bl_idname = 'projector.open_presets_folder'
    bl_label = 'Open My Presets Folder'

    def execute(self, context):
        folder = user_dir(create=True)
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


classes = (
    PROJECTOR_MT_models,
    PROJECTOR_MT_lenses,
    PROJECTOR_OT_apply_model,
    PROJECTOR_OT_apply_lens,
    PROJECTOR_OT_clear_model,
    PROJECTOR_OT_save_preset,
    PROJECTOR_OT_open_presets_folder,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
