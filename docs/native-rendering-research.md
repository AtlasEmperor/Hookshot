# Hookshot: research on native 4K, 240 Hz and HDR

**Status of the research.** The objective is an image actually computed at 3840 × 2160, at 240 images/s or more, with HDR, without upscaling, DLSS or frame generation.  
The research shows exploitable mechanisms and several precise defects; it does not yet demonstrate this combination in game.

The Hookshot revision taken into account is `7b817526d2e459a4881cac09cb4f9cfe84fd82fb`.  
The analyses below remain tied to the pinned versions named in their links, mainly Hookshot `97e7c55` and `3f5b0aa`, Rhino `5a96e6a`, Ocarina `14566bd` and TotK `ae30a61`.  
They do not constitute an exhaustive revalidation of this head.

**Code of Hookshot at `7b817526`.** For output and HDR, this code takes precedence over the analyses below: Hookshot offers the 5120 × 2880 output (`host/nn_applet.c`, `gpu/vk/vk_menu.cpp`) and an HDR10 surface when the HDR option is enabled and the display lists that surface (`gpu/vk/vk_main.cpp`).  
The 2560 × 1440 constants and the Rhino HDR paths cited below describe the versions pinned in their links, not this code.

The labels **verified code**, **CPU test**, **result announced by the author** and **proposal** indicate different levels of evidence.  
No game or downloaded binary was run for this research.

## 1. Contract: what must be truly native

The contract must be verifiable in the resources and GPU commands: main colour and depth at 3840 × 2160, final composition keeping that definition, presentation without spatial enlargement, and a new image fully rendered for each counted frame.  
A 4K swapchain, a “200%” setting or a presentation counter is not enough.

Auxiliary effects such as bloom, shadows or exposure measurement may keep their specific resolutions.  
Any anti-aliasing must work at constant resolution.  
Any reconstruction of a less-defined main scene must be disabled, including that of the original game: disabling only DLSS on the host does not guarantee this property.

At 240 images/s, the budget is **4.167 ms per frame**.  
A single 4K image represents 8,294,400 pixels, or about **1.99 billion pixels per second** at this rate, before overdraw, lighting and post-processing.  
This calculation sizes the objective; it does not predict any GPU able to reach it.

**Proposed architecture:** a common policy for resolution, rate and colour; game adapters validated per version; platform adaptations limited to the real capabilities of the display.  
NVIDIA and AMD must follow the same native path.  
The program must report the dimensions actually obtained when a configuration fails.

## 2. Effective resolutions, HeapDef and TAAU conversion

### The value 2048 × 1152 is not a universal base

The [Hookshot configuration code](https://github.com/NotRexed/Hookshot/blob/97e7c55f9cadcdf33bbbce1569950bbec36687ee/nx2/oot_wide.py) contains output constants 2560 × 1440 and a scene configuration of 1920 × 1080.  
[PR #578](https://github.com/NotRexed/Hookshot/pull/578) additionally identifies a table of modes with factors 1, 0.8 and 2/3.  
A 0.8 mode can therefore produce 2048 × 1152 from 2560 × 1440, even with the controller set to “100%”.

One must track separately the configuration, the active mode, the controller decision, scene allocations, post-processing output and the presented image.  
The mathematical factors 1.5 from 2560 × 1440 and 1.875 from 2048 × 1152 do not by themselves define a complete correction.

The [patch of #578](https://github.com/oscarrc91/Hookshot/blob/484bcffeab27a591bf8b8baa80238e4d188d7751/nx2/oot_native_resolution.py) checks the expected tables, changes only the 0.8 entry and keeps the original notifications for resource recreation.  
The author announces colour, depth and dispatch at 2560 × 1440, but the prototype combines other changes, including FSR.  
The isolated in-game behaviour remains to be validated; this PR brings neither a 4K output nor heap enlargement.  
Its refresh mechanism is relevant; FSR remains out of scope.

At Ocarina, [PR #68](https://github.com/sostenesfreitas/ocarina-recomp/pull/68) exposes fixed percentages from 25 to 200, with prior initialization of the controller.  
Values above 100 are explicitly not validated; the announced automatic/100% comparison on an RTX 5090 does not prove native 4K.  
The presence of a resolution file inherited from TotK does not show that a set of output and heap patches exists for OoT.

### Enlarge the right allocator before creating the images

At Rhino, the [resolution hooks](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/nx2/oot_patches.py) cover several levels: controller, caller, capping and dimension calculation.  
The code keeps a cap at 1.25 of the observed 2048 × 1152 scene.  
A comment reports a post-processing allocation failure with 1.875; removing this cap alone therefore does not solve the problem.

In Hookshot, raising the [announced application memory](https://github.com/NotRexed/Hookshot/blob/97e7c55f9cadcdf33bbbce1569950bbec36687ee/host/hos_mem.c) does not automatically resize the child graphics heaps.  
The game chooses the NVN pools and their offsets; [NVN computes the storage requirements](https://github.com/NotRexed/Hookshot/blob/97e7c55f9cadcdf33bbbce1569950bbec36687ee/host/nvn_native.c) before texture initialization; Vulkan then allocates its resources.  
Changing only the extent of a Vulkan image after this step exposes inconsistencies in pitch, mipmaps, aliasing, copies and CPU reads.

The [OoT path of NX2navi](https://github.com/tangerineturtle1/NX2navi/blob/42ae87bca62d657419c3b7f8e04f4a438e0aff1b/runtime/widescreen.c) provides a concrete lead: `Product.Nin_Ounce_NVN2.HeapDef.byml.zs`, a `DynamicTextureAllocatorMem` documented at 312,320 KiB, that is 305 MiB, and its parent `Graphics`.  
These names and sizes must be confirmed in the version of the game one owns.  
The [TotK path](https://github.com/valentderah/totk-pc-recomp/blob/ae30a61b7bee4a3db959a234e7459e95939ac596/runtime/resolution.c) shows a reusable method: enlarge child, parent and application budget consistently.  
Its constants and addresses are not those of OoT.

NX2navi's additions are covered by an [“all rights reserved” licence](https://github.com/tangerineturtle1/NX2navi/blob/42ae87bca62d657419c3b7f8e04f4a438e0aff1b/LICENSE-ADDITIONS).  
No code is copied from it; implementations must be independent or come from compatible sources.

**CPU test performed:** a fixture calls the real [`nvn_tex_layout` calculator](https://github.com/NotRexed/Hookshot/blob/97e7c55f9cadcdf33bbbce1569950bbec36687ee/host/nvn_layout.c), compiled as C11, over 24 cases.  
For 3840 × 2160, one layer, one mip and one sample:

| Format | Linear storage | NVN tiled storage |
|---|---:|---:|
| RGBA8, RGB10A2 or D32F | 31.641 MiB | 31.875 MiB |
| RGBA16F | 63.281 MiB | 63.750 MiB |

RGB10A2 HDR10 therefore does not require twice the memory of RGBA8.  
The number of simultaneous images and the Vulkan requirements remain to be measured.  
The [TotK PR #792](https://github.com/valentderah/totk-pc-recomp/pull/792) indeed shows Vulkan sparse requirements larger than the NVN logical storage; this mechanism requires specific alignment and lifetime management.

### Remove the reconstruction without removing the necessary conversion

The [Hookshot TAAU shader](https://github.com/NotRexed/Hookshot/blob/97e7c55f9cadcdf33bbbce1569950bbec36687ee/gpu/vk/shaders/taau_upscale.comp) receives RGB9E5 representing the square root of the scene light, squares the components and writes R11G11B10F.  
A raw copy at this boundary would be incorrect.  
At equal dimensions, an exact texel-for-texel conversion is possible, preserving exposure and history usages.

Replacing only the last dispatch does not automatically remove the earlier computations of the TAAU/HMMA network.  
One must establish which outputs remain consumed before removing those passes.  
The [Rhino substitution targets](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/gpu/vk/vk_dlss.cpp), limited to certain colour surfaces and tied to the DLSS path, are not a universal virtualization of resources.  
The priority route is to pass the correct dimensions to the engine before allocation.

## 3. 240+ clocks, physics and inputs

The [Hookshot PR #340](https://github.com/NotRexed/Hookshot/pull/340) links presentation rate and the game's time step.  
The version examined caps at 120 Hz.  
The author reports about 70 native images/s on an RTX 5090, with generation disabled; this demonstrates neither 120 nor 240 images/s, nor identical physics in all situations.

Two CPU tests show why a simple raise of the cap would be insufficient:

| Mechanism examined | Reproducible result | Consequence |
|---|---|---|
| Smoothing `oot_dyn_dt` of [Ocarina](https://github.com/sostenesfreitas/ocarina-recomp/blob/14566bd441301068a807cdfc3373aa1219f456d1/tools/oot/patch_generated.py) | After stabilization, a sustained transition 120 → 30 or 240 → 60 applies about 2.5 seconds for 10 real seconds. | The rejection of overly large intervals can remain blocked; distinguish sustained slowdown, pause and isolated incident. |
| [Compact publication of #340](https://github.com/monsterlag/Hookshot/blob/38ecf724f3cef6f30b5043fc5920f38b3308b54c/host/hos_rate_policy.h) | The nominal rate occupies eight bits. An experimental change of the cap alone to 360 corrupts several values from 256. | Provide a sufficiently wide representation, possibly rational. This defect is not reachable with the original cap of 120. |

These results concern isolated helpers, not a measurement of full-game speed.  
A common policy should publish rate and state generation consistently, handle regime changes and explicitly define the treatment of lost time.  
Modes 60, 120 and 240 must use this same policy.

Physics requires a separate validation.  
[TotK lowered its cap to 240](https://github.com/valentderah/totk-pc-recomp/commit/cad5b0cc39699f358b1686ad32119c0871c3427a) after Havok failures at shorter steps in certain saves.  
This precedent proves no identical limit in OoT.  
A possible decoupling of rendering and physics requires an audit of the engine's time consumers.

Inputs also deserve follow-up: the [mouse/controller path](https://github.com/NotRexed/Hookshot/blob/3f5b0aa505709a5e031382c00ecdc1c9fd95e4ef/host/nn_hid.c) contains a 10 ms mouse rate and a 2 ms read cache.  
These are not rendering caps.  
Events must be timestamped, accumulated movements consumed, and damping made independent of the frame count.

Finally, changing the system clock globally would also affect audio, video and synchronization.  
The correction must target the relevant simulation step and pacer.  
The [NX2navi report #71](https://github.com/tangerineturtle1/NX2navi/issues/71), describing an introduction speed dependent on the cap despite normal audio, recalls that a 240 Hz selector does not validate this separation; this report remains a user observation not reproduced here.

## 4. HDR independent of DLSS: possibilities and Rhino audit

The [Rhino HDR code](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/host/nn_vi.c) enables the game's HDR path and presents its RGB10A2/PQ output in HDR10.  
This mechanism requires neither NGX nor DLSS.  
The author announces validation on an HDR10 television with an RTX 5080, with and without DLSS; the internal definition and 240 images/s remain unestablished.

The audit identifies the following corrections before integration:

| Area | Finding and required correction |
|---|---|
| SDR/HDR switch | The swapchain change can precede the game's adaptation. Associate the encoding with each frame and convert the transitions explicitly. |
| State publication | `swap_hdr` is changed before the creation succeeds. Publish format, colour space and effective state together, after success. |
| Dark interface | The GDI conversion LUT quantizes too early. Use a precise PQ conversion when refreshing the interface. |
| Reference white | The environment variable and the menu can supply different values. Share a validated effective configuration. |
| Lifetime | The ring of four images is normally protected by the three presentation fences. No premature release has been demonstrated; resizing and acquisition failures remain cases to validate. |
| Platforms | The examined path enables the HDR extension only under Windows and selects a single RGB10A2 order. Query the formats actually available on each surface. |

Sources: [swapchain creation](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/gpu/vk/vk_main.cpp), [presentation](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/gpu/vk/vk_replay.cpp) and [interface](https://github.com/rhino-oot/Hookshot/blob/5a96e6a18bb22c4deb4a426897de5728b736b4de/gpu/vk/vk_menu.cpp).

**CPU test performed:** the real interface conversion, compiled in a fixture, gives for an sRGB grey of value 1 and a white at 200 nits a PQ10 code equal to 0, against 51 with the reference formula.  
This defect concerns the interface LUT, not directly the game image.

**Proposal:** after the game's final HDR curve, a direct 1:1 copy may replace the intermediate image and the blit if encoding, channel order, crop, Vulkan usages and synchronization match exactly.  
This copy concerns the RGB10A2 already PQ-encoded, never the earlier RGB9E5 conversion.  
At 4K/240, removing one read and one write of four bytes per pixel theoretically represents 15.93 GB/s; no GPU gain has been measured.

The [TotK HDR path](https://github.com/valentderah/totk-pc-recomp/blob/ae30a61b7bee4a3db959a234e7459e95939ac596/runtime/vk_hdr.c) provides useful references for SDR transitions, formats and diagnostics.  
Its tone-mapping curve must not be transplanted blindly.  
The [Vulkan HDR metadata](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_hdr_metadata.html) complement PQ encoding; their absence does not automatically make the output invalid.

## 5. Performance: order of priorities

The proposed order is as follows:

1. **Instrument the boundaries.** Dimensions, encoding, identifier of the image actually rendered, CPU/GPU time and memory must be correlatable.
2. **Establish native at a moderate rate.** HeapDef budget, controller, depth, post-processing and output must respect the contract before aiming at 240. Start with a resolution chosen at startup; changes during play will require removing old resources after fences and a consistent reset of the histories.
3. **Make scheduling reliable.** [PR #485](https://github.com/NotRexed/Hookshot/pull/485) studies releasing the virtual core during certain GPU waits. Our CPU fixture reproduced two failures of the previous behaviour and validated nine cases of the proposed behaviour, without measuring an in-game gain.
4. **Reduce demonstrably unnecessary work.** Examine residual TAAU, final transfers, [binding cache #423](https://github.com/NotRexed/Hookshot/pull/423) and [descriptors #435](https://github.com/NotRexed/Hookshot/pull/435), after profiling.
5. **Bound the resources.** [PR #479](https://github.com/NotRexed/Hookshot/pull/479) concerns the retention of host imports. Game heap, imported memory and GPU memory are distinct budgets; a removal heuristic does not replace proof of end of use.
6. **Raise the rate progressively.** Measure median and high-percentile times, shader compilation, distinct images presented and input latency, with heavy captures disabled.

These PRs are historical leads examined, not a selection to merge in full.  
The captures announced in [TotK #573](https://github.com/valentderah/totk-pc-recomp/pull/573) prove the value of acting on the controller and allocations, but their performance is not transferable to Hookshot.

## 6. Remaining checks and acceptance criteria

Still missing: the exact fingerprints of the targeted game, the HeapDef actually loaded, its overlays, the identity of the failing allocator, and a capture of the dependencies between passes.  
Traces must show dimensions, format, pitch, mips, layers, samples, pool, offset and lifetime, notably in the pause menu and during zone changes.

The next tests must cover HeapDef parsers with invalid sizes and arithmetic overflows, patches with absent or duplicated anchors, then colour and 1:1 coordinate conversions.  
A synthetic Vulkan validation must exercise RGB10A2 formats, crops, SDR/HDR transitions, resizes and resource removal after fences.

In game, compare movement speed, jumps, physical contacts, animations, menus, cutscenes and audio synchronization at 60, 120 and 240.  
Check sustained slowdowns and rate changes.  
For HDR, check texture values and a correctly configured display; the existing 8-bit PNGs are not enough to measure luminance and preservation of highlights.

Acceptance must therefore rest on three combined proofs: native definition preserved at each main boundary, rate of really rendered images without temporal drift, and correct HDR transport to the screen.  
The next step is a common, instrumented implementation, validated boundary by boundary before any performance promise.
