# Heroes of Might and Magic I — AGG Extractor

A Python tool for extracting and decoding all asset files from the `HEROES.AGG` archive used by Heroes of Might and Magic I.

Update: C++ 17 version for Mac/Unix also added

## Requirements

```bash
pip install Pillow
```

## Usage

```bash
python homm1_extract.py heroes.agg
```

```bash
python homm1_extract.py editor.agg
```

All files are extracted into a subdirectory named after the archive (e.g. `heroes/`). Image files are decoded to PNG. Sound files are converted to WAV. Raw data files are saved verbatim.

Tested on the HEROES.AGG file from the retail version from good old games (GOG), the windows 95 editor (editor.agg), and the HOMM 1 Demo version HEROES.AGG files. The demo is included in the repository. The AGG files seem to be identical for the Demo and the full game. I believe the demo version would only let you play 1 month in game time, so 28 days.

---

## C++ 17 Version Build Instructions
The C++ version is found in the cpp/ folder of this project.

On MacOS:
```bash
brew install cmake
brew install sdl2 sdl2_mixer sdl2_image

mkdir build

cd build

cmake .. && make -j$(sysctl -n hw.ncpu)
```

On Windows:
Install vcpkg if you don't have it
```dos
git clone https://github.com/microsoft/vcpkg.git C:\dev\vcpkg
C:\dev\vcpkg\bootstrap-vcpkg.bat
```
Install zlib for x64 Windows
```dos
C:\dev\vcpkg\vcpkg install zlib:x64-windows
```

Then build homm1 executable:
```dos
rmdir /s /q build
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=C:\dev\vcpkg\scripts\buildsystems\vcpkg.cmake -DVCPKG_TARGET_TRIPLET=x64-windows
cmake --build build  --parallel
```

Unix version is untested right now, but theoretically, to use it, rename CMakeLists_unix.txt to CMakeLists.txt and make sure you have Cmake and zlib installed.

## Usage

Assuming Heroes.agg is copied into the program directory (one level below build/):
```bash
./homm1 ../Heroes.agg 
```

On windows, the executable appears at build/Debug/homm1.exe 
I test it there by copying Heroes.agg to build/Debug/ and running:

```dos
./homm1.exe Heroes.agg
```
and the output is extracted to the Heroes directory.

---

### AGG — Aggregate Archive

The `.agg` file is a flat binary archive containing all game assets concatenated together with a small metadata header.

**Overall structure:**

| Section | Description |
|---|---|
| `u16` | Number of files `n` |
| `n × 14 bytes` | FileInfo table (see below) |
| File data | All file contents concatenated sequentially |
| `n × 15 bytes` | Filename table at the very end of the file |

**FileInfo record (14 bytes each):**

| Field | Type | Notes |
|---|---|---|
| Hash | `u32` | CRC hash of the filename (not used for extraction) |
| Unknown | `u16` | Purpose unknown; ignored |
| Size | `u32` | Size of the file in bytes |
| Size (duplicate) | `u32` | Identical to the size field above |

File offsets are **not stored** in the FileInfo records. Instead, file data is laid out sequentially in the same order as the FileInfo table, starting immediately after the table ends. Offsets are computed by accumulating sizes as you walk the table.

**Filename record (15 bytes each):**

13-character null-terminated DOS-compatible filename, followed by 2 bytes of padding. The filename table sits at the very end of the `.agg` file: `name_table_start = len(file) - 15 * n`.

> **Note:** This differs from Heroes of Might and Magic II, which uses 12-byte FileInfo records that include an explicit offset field.

---

### PAL — Palette

There is one file type: `kb.pal` (Heroes I ships two identical copies).

- 768 bytes total: 256 × 3 bytes of RGB color data
- Each channel is stored in the range 0–63; **multiply by 4** to get the actual 0–255 display value
- This palette must be loaded before any ICN, TIL, or BMP files can be decoded

**Color cycling ranges** (used for animation in-game, informational only):

| Range | Effect |
|---|---|
| 214–217 | Red / fire cycling |
| 218–221 | Yellow cycling |
| 231–237 | Ocean / river / lake |
| 238–241 | Blue cycling |

The first and last 10 palette entries and index 36 are black. Nineteen entries are reserved for cycling, leaving 217 colors available for artwork.

**Editor.agg**
The editor was built with a richer palette — 256 colors with extra bands for purples, light pinks, bright greens, and vivid blues. The portraits in editor.agg were re-painted against this richer palette. My theory is that the original game was created for DOS, and the editor was created for Windows 95 and got a palette upgrade.

---

### ICN — Sprites

ICN files contain one or more sprites (animation frames). Each ICN file decodes to a directory of numbered PNG files plus a `spec.xml` metadata file.

**ICN file layout:**

| Field | Type | Description |
|---|---|---|
| `n_sprites` | `u16` | Number of sprites in this file |
| `total_size` | `u32` | Total data size excluding these 6 header bytes |
| Sprite headers | `n × 12 bytes` | One per sprite (see below) |
| Pixel data | variable | All sprites' pixel data concatenated |

**Sprite header (12 bytes):**

| Field | Type | Description |
|---|---|---|
| `offsetX` | `s16` | Hotspot X offset for game engine positioning |
| `offsetY` | `s16` | Hotspot Y offset for game engine positioning |
| `width` | `u16` | Sprite width in pixels |
| `height` | `u16` | Sprite height in pixels |
| `packed` | `u32` | High byte = sprite type; low 24 bits = `data_off` |

The `packed` field encodes two values:
- **type** = `packed >> 24` — `0` for normal color sprites, `32` for monochrome
- **data_off** = `packed & 0x00FFFFFF` — byte offset of this sprite's pixel data, **relative to byte 6 of the ICN file** (i.e. right after the 6-byte global header)

> **Important:** Sprite headers are not necessarily stored in the same order as their pixel data on disk. The `data_off` values may not be monotonically increasing. The end boundary for each sprite's data is found by sorting all `data_off` values and taking the next larger value, rather than assuming `headers[i+1]` is adjacent on disk.

**Pixel encoding — normal sprites:**

| Byte value | Meaning |
|---|---|
| `0x00` | End of line — advance to start of next row |
| `0x01`–`0x7F` | Literal run — next `N` bytes are palette color indices |
| `0x80` | End of sprite data |
| `0x81`–`0xFF` | Skip `N - 0x80` transparent pixels |

> **HoMM1 vs HoMM2:** Online documentation for the ICN format often describes additional commands in the `0x81`–`0xFF` range (shadow pixels, RLE runs, sub-commands at `0xC0`–`0xFF`). Those commands exist in **Heroes of Might and Magic II** but not in HoMM1. In HoMM1 the entire `0x81`–`0xFF` range is purely a transparent pixel skip. Using the HoMM2 interpretation on HoMM1 data produces corrupted sprites. This was verified empirically by decoding `strip.icn` sprite 0 (a 640×212 UI panel background): with the HoMM2 scheme the `0xC0`–`0xFF` bytes were misread as RLE/shadow commands, leaving most rows short; with the simple skip the sprite decodes correctly to the full-width gold-bordered panel frame seen in-game.

**Pixel encoding — monochrome sprites (type = 32):**

| Byte value | Meaning |
|---|---|
| `0x00` | End of line |
| `0x01`–`0x7F` | `N` black (fully opaque) pixels |
| `0x80` | End of sprite data |
| `0x81`–`0xFF` | Skip `N - 0x80` transparent pixels |

All unspecified pixels default to fully transparent. `offsetX`/`offsetY` are written to `spec.xml` for reference but do not affect the PNG canvas size — the PNG is always exactly `width × height` pixels.

---

### TIL — Tiles

TIL files contain rectangular tiles used for map terrain.

**Layout:**

| Field | Type | Description |
|---|---|---|
| `n_tiles` | `u16` | Number of tiles |
| `width` | `u16` | Tile width in pixels |
| `height` | `u16` | Tile height in pixels |
| Pixel data | `n × width × height bytes` | Palette index per pixel, row-major |

Each tile is decoded to a separate numbered PNG using the loaded palette.

The archive contains three TIL files:

| File | Contents |
|---|---|
| `ground32.til` | All terrain types for the main adventure map |
| `clof32.til` | Four dark tiles (night sky) |
| `ston.til` | Stone ground tiles |

---

### BMP — Background Images

HoMM uses a **custom BMP format** that is completely different from standard Windows BMP files. Do not attempt to open these with standard image software before decoding.

**Layout:**

| Field | Type | Description |
|---|---|---|
| Magic | `0x21 0x00` | Fixed identifier |
| `width` | `u16` | Image width in pixels |
| `height` | `u16` | Image height in pixels |
| Pixel data | `width × height bytes` | Palette index per pixel, row-major |

Each pixel value is an index into the 256-color palette loaded from `kb.pal`.

---

### STD — Creature Standing & Attack Animations

Each creature in the game has a `.std` file containing all frames needed for its idle and combat animations. The file uses the standard ICN encoding (same header format, same pixel encoding). The extractor decodes every frame to an individual PNG and additionally produces **composite attack frames** by combining the base pose with each attack overlay, using the `offsetX`/`offsetY` values from each sprite header to align them on a shared canvas.

#### Compositing

Every sprite in an ICN-family file shares a common anchor point at `(0, 0)` — conceptually the creature's feet or center-bottom. Each sprite header's `offsetX`/`offsetY` gives the position of that sprite's top-left corner relative to the anchor, with `offsetY` being negative (upward). To composite two or more sprites together the extractor:

1. Computes the bounding box that encloses all sprites: `min(offsetX)` to `max(offsetX + width)` and `min(offsetY)` to `max(offsetY + height)`.
2. Creates a transparent RGBA canvas of that size.
3. Pastes each sprite at `(offsetX − min_x, offsetY − min_y)`.

This produces a correctly aligned composite regardless of whether the overlay is taller, wider, or offset to either side of the base frame.

#### Standard frame layout (18 frames, most creatures)

| Frame | Role |
|---|---|
| F0 | Noise / ignored |
| F1 | Standing (idle) |
| F2 | Death |
| F3 | Attack frame 1 |
| F4 | Attack frame 2 |
| F5 | Base pose — used as the bottom layer for composite attack frames |
| F6 | Attack-up overlay |
| F7 | Attack-across overlay |
| F8 | Attack-down overlay |
| F9 | 1×1 sentinel (ignored) |
| F10–F13 | Shadow strips for F1–F4 |
| F14 | 1×1 sentinel (ignored) |
| F15–F17 | Shadow strips for F6–F8 |

The extractor outputs `composite_atk_up.png`, `composite_atk_across.png`, and `composite_atk_down.png` — each being F5 composited with the corresponding overlay frame.

#### Special case: flying creatures (gargoyle, griffin, ghost) + Wolf

For these four creatures, **F5 is not a full body sprite**. Instead it is a tiny patch of a few pixels — a shadow anchor that the game engine uses as a positional reference for the attack overlays. F6, F7, and F8 contain the complete creature art for each attack direction and are composited directly on top of this anchor. The resulting composite PNGs look correct: the small anchor contributes almost nothing visually, and the large overlay frames land at the right position on the canvas.

This was a non-obvious discovery during decoding. The tiny F5 dimensions (e.g. wolf's F5 is only 4×11 pixels) would have caused it to be silently discarded if it had been filtered out as a "shadow frame" — which would have broken the compositing for these creatures entirely. The fix was to keep all frames in the decoded sprite table regardless of size, and only filter small frames from the raw per-frame PNG output, not from the compositing step.

#### Special case: extended creatures (dragon, phoenix, cyclops)

These three creatures have **33 frames** instead of 18, providing three complete sets of attack overlays (representing different animation stages of a breath weapon or multi-part attack) rather than one:

| Frame | Role |
|---|---|
| F0–F4 | Noise, standing, death, attack 1, attack 2 (same as standard) |
| F5 | Base pose |
| F6–F8 | Attack overlay set 0 (up / across / down) |
| F9–F11 | Attack overlay set 1 |
| F12–F14 | Attack overlay set 2 |
| F15 | 1×1 sentinel |
| F16–F19 | Shadow strips for F1–F4 |
| F20 | 1×1 sentinel |
| F21–F29 | Shadow strips for overlay sets 0, 1, and 2 |
| F30–F32 | Additional shadow strips (identical copies of F27–F29) |

The extractor produces nine composite PNGs for these creatures: `composite_atk0_up.png`, `composite_atk0_across.png`, `composite_atk0_down.png`, and likewise for sets 1 and 2.

#### Special case: hydra

The hydra has **no base frame and no overlay compositing**. Its 16 frames are all independent full-body poses. The extractor outputs them as plain numbered PNGs with no composites.

| Frame | Role |
|---|---|
| F0 | Noise / ignored |
| F1–F7 | Seven independent animation frames |
| F8 | 1×1 sentinel |
| F9–F15 | Shadow strips for F1–F7 |

---

### WLK — Walk Animation / WIP — Death Animation

Walk cycle and death (wipe) animations use the same ICN encoding as all other sprite types. The extractor decodes them to a directory of numbered PNGs with a `spec.xml`. No compositing is performed — each frame is a standalone full-body pose.

---

### ATK — Ranged Attack Animations

`.atk` files cover creatures with ranged attacks (archer, druid, elf, centaur, orc, troll). They use the same ICN encoding and the same compositing approach as STD files.

**ATK frame layout:**

| Frame | Role |
|---|---|
| F0 | Base pose (always visible) |
| F1–F4 | Attack animation overlays, composited on top of F0 |
| F5–F9 | Projectile sprites (arrow, bolt, fireball, etc.) — exported individually |

The extractor outputs `composite_atk_F1.png` through `composite_atk_F4.png` (base + each overlay), plus `projectile_F5.png` through `projectile_F9.png` for whichever projectile frames are present. All frames are also exported as individual numbered PNGs.

---

### BKG — Battle Background

`.bkg` files are the sky-strip images shown at the top of the battle screen. They use exactly the same raw palette-indexed format as the custom BMP files.

**Layout:**

| Field | Type | Description |
|---|---|---|
| Magic | `0x21 0x00` | Same fixed identifier as BMP |
| `width` | `u16` | Image width (typically 640) |
| `height` | `u16` | Image height (typically 102) |
| Pixel data | `width × height bytes` | Palette index per pixel, row-major |

Each `.bkg` file is decoded to a single PNG named `<stem>_bkg.png`.

---

### XTL — Battle Hex Tiles

`.xtl` files contain the hex tile shapes used to build the battle grid. They use the standard ICN encoding (same header, same pixel commands, same `offsetX`/`offsetY` fields) and are decoded to a directory of numbered PNGs with a `spec.xml`.

A typical `.xtl` file contains 11 frames:

| Frames | Role |
|---|---|
| F0 | Left-edge partial tile (narrow) |
| F1 | Left-edge partial tile (alternate) |
| F2 | Right-edge partial tile |
| F3 | Right-edge partial tile (alternate) |
| F4 | Wide edge variant |
| F5–F10 | Full 78×99 hex tile variants (2 generic + 4 flavor/detail variants) |

The battle scene assembler (`homm1_battle_scene.py`) uses the full tile variants (F5–F10) weighted 75% generic and 25% flavor to randomly populate the grid, and the edge tiles (F0–F4) to fill the partial hexes at the left and right borders.

---

### OBJ — Battle Scene Objects

`.obj` files contain the decorative objects placed on the battle grid — trees, rocks, ruins, and similar terrain features. They use the standard ICN encoding and are decoded to a directory of numbered PNGs with a `spec.xml`.

Each frame in an `.obj` file is an independent object sprite. The `offsetX`/`offsetY` values in the sprite headers give the anchor offset so the object can be correctly centered on its hex tile by the battle scene assembler.

---

### 82M — Sound Effects

`.82m` files are raw PCM audio. The extractor converts them directly to standard WAV files using Python's built-in `wave` module — no additional dependencies required.

**Format detection:** The extractor first checks whether the file begins with the four-byte magic `"82M "`. If present, the sample rate (`u32`), channel count (`u16`), and bit depth (`u16`) are read from the following 8 bytes. If the magic is absent — which is the normal case for HoMM1 AGG files — the extractor falls back to the observed defaults:

| Parameter | Default |
|---|---|
| Sample rate | 11025 Hz |
| Channels | 1 (mono) |
| Bit depth | 16-bit signed PCM |

Each `.82m` file is saved as `<stem>.wav` alongside all other extracted assets. If WAV conversion fails for any reason the raw bytes are saved as a fallback so nothing is lost.

> If a converted WAV sounds wrong (wrong pitch or noise), the file likely uses 8-bit unsigned PCM instead of 16-bit. The defaults `_82M_BITS_PER_SAMPLE` near the top of the decoder function can be adjusted per-file.

---

## Output Structure

```
heroes/
├── palette_swatch.png          # Visual color swatch of the loaded palette
├── kb.pal                      # Raw palette file
├── overmain.png                # Decoded BMP backgrounds
├── ground32/                   # Decoded TIL tiles (one PNG per tile)
│   ├── 0000.png
│   └── ...
├── advmice/                    # Decoded ICN sprites (one PNG per frame)
│   ├── 0000.png
│   ├── spec.xml                # Sprite metadata (offsets, sizes, types)
│   └── ...
├── archer.std/                 # Decoded STD creature animation frames
│   ├── 0001.png                # Standing
│   ├── 0002.png                # Death
│   ├── 0003.png                # Attack frame 1
│   ├── 0004.png                # Attack frame 2
│   ├── 0005.png                # Base pose
│   ├── 0006.png                # Attack-up overlay (raw)
│   ├── 0007.png                # Attack-across overlay (raw)
│   ├── 0008.png                # Attack-down overlay (raw)
│   ├── composite_atk_up.png    # Base + attack-up composited
│   ├── composite_atk_across.png
│   ├── composite_atk_down.png
│   └── spec.xml
├── dragon.std/                 # Extended creature (3 attack sets)
│   ├── composite_atk0_up.png
│   ├── composite_atk0_across.png
│   ├── composite_atk0_down.png
│   ├── composite_atk1_up.png   # ... and so on for sets 1 and 2
│   └── ...
├── archer.atk/                 # Decoded ATK ranged attack frames
│   ├── composite_atk_F1.png    # Base + overlay composited
│   ├── composite_atk_F2.png
│   ├── composite_atk_F3.png
│   ├── composite_atk_F4.png
│   ├── projectile_F5.png       # Arrow / bolt sprite
│   └── spec.xml
├── grass.xtl/                  # Decoded battle hex tiles
│   ├── 0000.png                # Edge tile variants
│   ├── 0005.png                # Full hex tile (generic)
│   └── spec.xml
├── grass.obj/                  # Decoded battle scene objects
│   ├── 0000.png
│   └── spec.xml
├── frstwgrs_bkg.png            # Decoded battle background sky strip
├── wsnd00.wav                  # Converted sound files (WAV)
└── ...                         # All other files saved verbatim
```

---

## Known Limitations

- Some sprites in the archive have truncated pixel data. These are decoded as far as possible and the remaining pixels are left transparent.
- Color cycling (palette animation) is not simulated — exported PNGs show the static palette colors.
- If a `.82m` WAV conversion produces noise or wrong pitch, the file may use 8-bit unsigned PCM rather than the default 16-bit. Adjust `_82M_BITS_PER_SAMPLE` in the source.

## Credits

Written by Andrew G. Stevens with assistance from Claude Sonnet 4.6.

Attribution also goes to some Java code from James Koppel about the HOMM2 AGG format and some notes derived from it here:
https://thaddeus002.github.io/fheroes2-WoT/infos/informations.html - there were some minor differences and errors that were debugged and have been documented here and in the code.

## License

This code is released under the Apache License, Version 2.0.
