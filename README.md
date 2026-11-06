# Projector Add-on for Blender
Simple projector creation and modification for [Blender](https://www.blender.org/).

![Projector Add-on for Blender title image](/.github/gifs/title.jpg)

## What this Add-on can do for you
* Easy creation and modification of physically-based projectors.
* Real-world projector settings like [throw ratio](https://en.wikipedia.org/wiki/Throw_(projector)), [resolution](https://en.wikipedia.org/wiki/Computer_display_standard) and [lens shift](https://www.projectorcentral.com/Understanding-Lens-Offset-and-Lens-Shift.htm).
* Project test textures or your own content like images and videos.
* Preview the projections in Cycles and EEVEE (including Material Preview in the viewport).

### EEVEE
EEVEE ignores node trees on lights, so in EEVEE the projection is done in the materials of the receiving objects:

1. Select the objects to project onto, then the projector.
2. In the *Projector* panel under *EEVEE & Material Preview*, click **Add Selected** (or **Add All** for every visible object).

The addon adds the projector to those materials through an EEVEE-only Material Output, so Cycles renders are unchanged. Brightness, falloff, throw ratio, lens shift, resolution, checker color, custom images/movies and the pixel grid follow the projector settings. Moving, animating or hiding the projector (render visibility) updates EEVEE live. Use **Remove Selected/All** to restore the original materials. Deleting a projector cleans up after itself.

### Duplicating
Shift+D (or copy/paste) a projector and the copy becomes a complete, independent projector with the same settings, custom image, body and EEVEE receivers. The **Duplicate** button next to New/Remove does the same and places the copy beside the original.

### Reinit
If a projector breaks (node trees edited by hand, its light deleted, its node removed from a material), select it and click **Reinit**. It rebuilds the projector from its settings and keeps its custom image, body and EEVEE receivers.

### Deleting
Delete a projector with the Remove button, X or the Outliner: its spot light, body, EEVEE setup and shadow map are removed with it, and receiving materials are restored.

### Projector body
Tick **Show Body** to add a box for the projector housing behind the lens, with its **Width**, **Height** and **Depth**. **Lens Offset** moves the lens away from the centre of the front face, for projectors whose lens is off-centre. Clicking the body selects its projector. The body renders, blocks other projectors' beams (Cycles, and EEVEE with shadows), and never blocks its own projector.

#### Shadows
Tick **Shadows** to let objects block the projection. The addon ray-casts the scene from the projector into a depth map (shadow mapping, done offline) and the projection only lands where nothing is in front. Every visible object casts shadows, receiver or not, except objects with *Shadow* ray visibility turned off or hidden from render.
* **Auto Update** re-bakes shortly after objects stop moving. A 1024 map typically takes well under a second.
* **Resolution** sets how sharp the shadow edges are. **Bias** fixes speckled self-shadowing on surfaces the beam hits at a steep angle.
* The map is saved in the .blend.

Limitations in EEVEE:
* Shadows come from the last bake. Rendering an animation where the projector or set moves uses the shadows of the frame that was baked.
* Only diffuse light (no projected highlights). The surface color comes from the Base Color of a Principled BSDF or the Color of a Diffuse BSDF; other shaders get a light grey.
* Materials are shared, so every object using a receiving material gets the projection.

## Projectors Add-on in Action

#### Throw Ratio
Control the size of your projection by adjusting the throw ratio to match real-world projector specifications.
![Throw Ratio](/.github/gifs/throw_ratio.gif)

#### Lens Shift
Fine-tune the vertical and horizontal position of your projection without moving the projector itself.
![Lens Shift](/.github/gifs/lens_shift.gif)

#### Image Textures & Resolution
Load your own images or videos and set custom resolutions to match your projection content.
![Image Texture & Resolutions](/.github/gifs/image_textures_resolution.gif)

#### Random Color
Quickly assign random colors to distinguish multiple projectors in your scene.
![Random Color](/.github/gifs/random_color.gif)

## Note
* works with Blender 2.8 and up

## Wiki
* A growing [wiki](https://github.com/Ocupe/Projectors/wiki) to help users with this add-on. If you have problems or feel that something is missing, please feel free to request more content.

## Installation
* Download the repo by clicking the green **Code** button and then **Download ZIP** (don't unpack the file on your computer).
* Open Blender.
* Go to the User Preferences in the Addon tab.
* Click Install from File and choose the zip file you downloaded.
* Activate the add-on by clicking on the checkbox.

## Missing something?
I'm interested and open to suggestions. Let me know how you use the add-on and how it could improve. Open an issue or message me.

P.S. Germans like to call a projector, a beamer.
