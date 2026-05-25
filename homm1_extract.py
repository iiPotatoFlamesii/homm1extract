#!/usr/bin/env python3
"""
Heroes of Might and Magic I - AGG file extractor.

Extracts all files from HEROES.AGG and decodes:
  - ICN  -> PNG sprites (RGBA, with transparency)
  - WLK  -> PNG sprites (walk animation frames, same ICN encoding)
  - STD  -> PNG sprites (standing/idle animation frames, same ICN encoding)
             + composite attack frames (base + overlay) using spec.xml offsets
             + shadow composites alongside body composites
  - WIP  -> PNG sprites (wipe/death animation frames, same ICN encoding)
  - ATK  -> PNG sprites (attack animation frames, same ICN encoding)
             + composite attack frames (base + overlay) using spec.xml offsets
             + projectile frames (F5-F9) extracted individually
  - TIL  -> PNG tiles
  - BMP  -> PNG images (HoMM palette-indexed format, NOT standard BMP)
  - PAL  -> raw palette saved + palette_swatch.png for inspection
  - 82M  -> raw sound data saved as-is
  - everything else -> saved verbatim

Usage:
    pip install Pillow
    python homm1_extract.py heroes.agg

Output goes into a directory named after the .agg file (e.g. 'heroes/').


## STD frame layout (standard 18-frame creatures)

  F0  : noise – skip
  F1  : standing body
  F2  : death body
  F3  : attack frame 1 body
  F4  : attack frame 2 body
  F5  : base body (full pose used as bottom layer for F6–F8)
          For flying creatures (gargoyle, griffin, ghost, wolf) this is a
          small shadow-anchor patch rather than a full body sprite.
  F6  : attack-up overlay    (composited on top of F5)
  F7  : attack-across overlay
  F8  : attack-down overlay
  F9  : 1×1 sentinel (ignored)
  F10 : shadow for F1
  F11 : shadow for F2
  F12 : shadow for F3
  F13 : shadow for F4
  F14 : 1×1 sentinel (ignored)
  F15 : shadow for F6 / attack-up
  F16 : shadow for F7 / attack-across
  F17 : shadow for F8 / attack-down

  No separate shadow exists for F5 (its shadow is the tiny anchor patch itself
  for flying creatures, or is absent for grounded ones).

  For extended creatures (dragon, cyclops, phoenix) there are 33 frames:
  F0–F14 : as above but overlays continue F6–F14 (3 sets of 3 directions)
  F15    : sentinel
  F16–F19: shadows for F1–F4
  F20    : sentinel
  F21–F32: four identical groups of 3 shadow frames (one per overlay direction
            set); only the first three groups are meaningful (sets 0–2 = F21–F29).

## ATK frame layout (ranged/melee attack sequences)

  F0  : base frame
  F1–F4: animation overlay frames
  F5–F9: projectile frames (separate sprites, exported individually)

  Composite outputs: base(F0) + each of F1–F4.

## Compositing

  All sprites in a single file share a common anchor point (0, 0).
  Each sprite header contains (offsetX, offsetY) which locate the sprite's
  top-left corner relative to that anchor.  To composite N sprites:

    canvas_left   = min(offsetX  for sprite in group)
    canvas_top    = min(offsetY  for sprite in group)
    canvas_right  = max(offsetX + width  for sprite in group)
    canvas_bottom = max(offsetY + height for sprite in group)
    canvas_size   = (canvas_right - canvas_left, canvas_bottom - canvas_top)

    paste sprite i at pixel (offsetX_i - canvas_left, offsetY_i - canvas_top)

  Shadow frames are composited separately alongside their body counterparts
  and saved with a _shadow suffix.


## Credits

Written by Andrew G. Stevens with assistance from Claude Sonnet 4.6.

Attribution also goes to some Java code from James Koppel about the
HOMM2 AGG format and some notes derived from it here:
https://thaddeus002.github.io/fheroes2-WoT/infos/informations.html -
there were some minor differences and errors that were debugged and
have been documented here and in the code.

## License

This code is released under the Apache License, Version 2.0.
"""

import struct
import os
import sys
import argparse
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not found. Images will not be decoded.")
    print("         Install with: pip install Pillow\n")


# ===========================================================================
# Binary read helpers (all little-endian)
# ===========================================================================

def u8(d, p):  return d[p], p + 1
def u16(d, p): return struct.unpack_from('<H', d, p)[0], p + 2
def u32(d, p): return struct.unpack_from('<I', d, p)[0], p + 4
def s16(d, p): return struct.unpack_from('<h', d, p)[0], p + 2


# ===========================================================================
# AGG parsing - Heroes I format
#
# Header: u16 n_files
# FileInfo table: n_files * 14 bytes each
#   u32  hash
#   u16  unknown
#   u32  size
#   u32  size (duplicate)
# File data: concatenated, sequential (no explicit offsets stored)
# Filename table: n_files * 15 bytes at end of file
#   13-char null-terminated DOS filename + 2 padding bytes
# ===========================================================================

def parse_agg(data):
    pos = 0
    n_files, pos = u16(data, pos)
    print(f"AGG contains {n_files} file(s).")

    # Read FileInfo records (14 bytes each)
    records = []
    for _ in range(n_files):
        fhash = struct.unpack_from('<I', data, pos)[0]; pos += 4
        _unk  = struct.unpack_from('<H', data, pos)[0]; pos += 2
        size  = struct.unpack_from('<I', data, pos)[0]; pos += 4
        _dup  = struct.unpack_from('<I', data, pos)[0]; pos += 4
        records.append({'hash': fhash, 'size': size})

    # File data starts immediately after the header table and is sequential
    offset = pos
    for r in records:
        r['offset'] = offset
        offset += r['size']

    # Filename table: last 15*n bytes of the file
    name_table_start = len(data) - 15 * n_files
    for i, r in enumerate(records):
        raw = data[name_table_start + i*15 : name_table_start + i*15 + 13]
        null = raw.find(b'\x00')
        raw = raw[:null] if null != -1 else raw
        r['name'] = raw.decode('ascii', errors='replace').strip()

    # Attach file contents
    for r in records:
        r['data'] = data[r['offset'] : r['offset'] + r['size']]

    return records


# ===========================================================================
# Palette (PAL)
#
# 768 bytes = 256 * 3 (RGB).
# Each channel is 0-63; multiply by 4 to get 0-255.
# ===========================================================================

def load_palette(pal_data):
    if len(pal_data) < 768:
        raise ValueError(f"PAL too small: {len(pal_data)} bytes (need 768)")
    return [
        (min(pal_data[i*3]   * 4, 255),
         min(pal_data[i*3+1] * 4, 255),
         min(pal_data[i*3+2] * 4, 255))
        for i in range(256)
    ]

def save_palette_swatch(palette, path):
    """Save a 256x32 colour swatch so you can visually inspect the palette."""
    if not PIL_AVAILABLE:
        return
    img = Image.new('RGB', (256, 32))
    px = img.load()
    for i, (r, g, b) in enumerate(palette):
        for y in range(32):
            px[i, y] = (r, g, b)
    img.save(path)


# ===========================================================================
# ICN sprite decoder
#
# File layout:
#   u16  n_sprites
#   u32  total_data_size  (= file_size - 6)
#   n_sprites * 12-byte sprite headers
#   sprite pixel data (contiguous)
#
# Sprite header (12 bytes):
#   s16  offsetX    -- hotspot offset for game engine (not canvas shift)
#   s16  offsetY
#   u16  width
#   u16  height
#   u32  dOffset    -- data offset (relative to file byte 6)
#
# Pixel encoding (normal sprites) - HoMM1 format:
#   0x00        end of line; advance to start of next row
#   0x01-0x7F   literal run: next N bytes are palette colour indices
#   0x80        end of sprite data
#   0x81-0xFF   skip (N-0x80) transparent pixels
#               Note: unlike HoMM2, there are no shadow or RLE commands.
#               The full 0x81-0xFF range is purely transparent skip.
#
# Pixel encoding (monochrome):
#   0x00        end of line
#   0x01-0x7F   N black pixels
#   0x80        end of sprite data
#   0x81-0xFF   skip (N-0x80) transparent pixels
# ===========================================================================

def _decode_one_sprite(icn_data, hdr, palette, mono=False):
    """
    Decode a single sprite from an ICN/STD/ATK/etc. file.

    Returns an RGBA PIL Image, or None if width/height is 0.
    Shadow frames (very short height, h <= 20) are decoded normally –
    the caller decides whether to use them.
    """
    if not PIL_AVAILABLE:
        return None
    sw, sh = hdr['w'], hdr['h']
    if sw == 0 or sh == 0:
        return None

    buf = bytearray(sw * sh * 4)  # RGBA, all zeros = fully transparent

    def set_px(px, py, r, g, b, a, _sw=sw, _sh=sh, _buf=buf):
        if 0 <= px < _sw and 0 <= py < _sh:
            base = (py * _sw + px) * 4
            _buf[base]   = r
            _buf[base+1] = g
            _buf[base+2] = b
            _buf[base+3] = a

    sorted_dofs = hdr['_sorted_dofs']

    def data_end(dof):
        for d in sorted_dofs:
            if d > dof:
                return 6 + d
        return len(icn_data)

    p     = 6 + hdr['dof']
    p_end = data_end(hdr['dof'])
    x, y  = 0, 0

    while p < p_end:
        cmd = icn_data[p]; p += 1

        if cmd == 0x00:
            x = 0; y += 1
        elif cmd == 0x80:
            break
        elif 0x01 <= cmd <= 0x7F:
            if mono:
                for _ in range(cmd):
                    set_px(x, y, 0, 0, 0, 255); x += 1
            else:
                for _ in range(cmd):
                    if p >= p_end: break
                    ci = icn_data[p]; p += 1
                    cr, cg, cb = palette[ci]
                    set_px(x, y, cr, cg, cb, 255); x += 1
        else:
            x += cmd - 0x80

    return Image.frombytes('RGBA', (sw, sh), bytes(buf))


def _read_icn_headers(icn_data):
    """
    Parse the ICN/STD/ATK header table.  Returns (n_sprites, headers_list).
    Each header dict has keys: ox, oy, w, h, type, dof, _sorted_dofs.
    """
    if len(icn_data) < 6:
        raise ValueError("ICN file too small")

    pos = 0
    n_sprites, pos = u16(icn_data, pos)
    _total_size, pos = u32(icn_data, pos)

    if n_sprites == 0:
        return 0, []

    headers = []
    for _ in range(n_sprites):
        ox,   pos = s16(icn_data, pos)
        oy,   pos = s16(icn_data, pos)
        w,    pos = u16(icn_data, pos)
        h,    pos = u16(icn_data, pos)
        pack, pos = u32(icn_data, pos)
        dof =  pack
        headers.append({'ox': ox, 'oy': oy, 'w': w, 'h': h,
                        'dof': dof, '_sorted_dofs': None})

    sorted_dofs = sorted(set(h['dof'] for h in headers))
    for h in headers:
        h['_sorted_dofs'] = sorted_dofs

    return n_sprites, headers


# ===========================================================================
# Compositing helper
# ===========================================================================

def _composite_sprites(images_with_headers):
    """
    Composite one or more (PIL Image, header) pairs onto a shared canvas
    using each sprite's (offsetX, offsetY) to position it.

    Returns the composited RGBA PIL Image.
    """
    if not images_with_headers:
        return None

    min_x = min(hdr['ox'] for _, hdr in images_with_headers)
    min_y = min(hdr['oy'] for _, hdr in images_with_headers)
    max_x = max(hdr['ox'] + hdr['w'] for _, hdr in images_with_headers)
    max_y = max(hdr['oy'] + hdr['h'] for _, hdr in images_with_headers)

    canvas_w = max_x - min_x
    canvas_h = max_y - min_y
    if canvas_w <= 0 or canvas_h <= 0:
        return None

    canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
    for img, hdr in images_with_headers:
        if img is None:
            continue
        px = hdr['ox'] - min_x
        py = hdr['oy'] - min_y
        canvas.alpha_composite(img, (px, py))

    return canvas


# ===========================================================================
# STD decoder
# ===========================================================================

# Creatures with tiny F5 (shadow anchor) – their overlays are composited
# directly without a large body base underneath.
_SHADOW_ANCHOR_CREATURES = {'wolf', 'gargoyle', 'griffin', 'ghost'}

# Extended creatures (dragon, cyclops, phoenix) have 3 sets of 3 attack
# overlays instead of just one set.
_EXTENDED_CREATURES = {'dragon', 'cyclops', 'phoenix'}

# Hydra has no base frame 5 and no overlay compositing – all 7 frames are
# independent full-body frames.
_HYDRA_LIKE = {'hydra'}


def decode_std(icn_data, palette, out_dir, stem):
    """
    Decode a STD file, write individual frame PNGs and composite attack
    frames (body + overlay using spec.xml offsets), plus shadow composites.
    """
    if not PIL_AVAILABLE:
        return

    n_sprites, headers = _read_icn_headers(icn_data)
    if n_sprites == 0:
        return

    os.makedirs(out_dir, exist_ok=True)

    creature = stem.lower()  # e.g. 'wolf', 'archer', 'dragon'

    # -----------------------------------------------------------------------
    # Decode all sprites up-front (including shadow frames – h <= 20 kept)
    # -----------------------------------------------------------------------
    sprites = {}   # idx -> PIL Image or None
    for idx, hdr in enumerate(headers):
        sprites[idx] = _decode_one_sprite(icn_data, hdr, palette)

    # -----------------------------------------------------------------------
    # Write individual frame PNGs (skip F0 noise, skip sentinels and shadows)
    # Shadow frames are thin (h <= 20) and only appear in indices >= 9.
    # Sentinel frames are 1x1.
    # -----------------------------------------------------------------------
    SHADOW_THRESHOLD = 20
    SENTINEL_SIZE    = 1

    for idx, img in sprites.items():
        if img is None:
            continue
        hdr = headers[idx]
        # Skip noise frame
        if idx == 0:
            continue
        # Skip 1x1 sentinels
        if hdr['w'] <= SENTINEL_SIZE and hdr['h'] <= SENTINEL_SIZE:
            continue
        # Skip shadow frames (thin stripes in the upper half of the index space)
        if idx >= 9 and hdr['h'] <= SHADOW_THRESHOLD:
            continue
        img.save(os.path.join(out_dir, f'{idx:04d}.png'))

    # -----------------------------------------------------------------------
    # Build composite attack frames
    # -----------------------------------------------------------------------

    if creature in _HYDRA_LIKE:
        # No compositing needed – all frames are independent
        _write_std_spec(out_dir, n_sprites, headers, [])
        return

    if creature in _EXTENDED_CREATURES:
        # F5 = base, F6-F8 = set0, F9-F11 = set1, F12-F14 = set2
        overlay_sets = [
            (6,  7,  8,  'atk0'),
            (9,  10, 11, 'atk1'),
            (12, 13, 14, 'atk2'),
        ]
    else:
        # Standard 18-frame creature: F5 = base, F6-F8 = single overlay set
        overlay_sets = [
            (6, 7, 8, 'atk'),
        ]

    composites = []  # list of (filename, anchor_comment) for spec

    def make_and_save(body_idx, overlay_idx, name):
        """Composite body+overlay and save PNG."""
        base_img = sprites.get(body_idx)
        base_hdr = headers[body_idx] if body_idx < len(headers) else None
        over_img = sprites.get(overlay_idx)
        over_hdr = headers[overlay_idx] if overlay_idx < len(headers) else None

        if base_img is None or over_img is None:
            return
        if base_hdr is None or over_hdr is None:
            return

        composite = _composite_sprites([(base_img, base_hdr),
                                        (over_img,  over_hdr)])
        if composite:
            out_path = os.path.join(out_dir, f'{name}.png')
            composite.save(out_path)
            composites.append(name)

    base_idx = 5

    for set_entry in overlay_sets:
        up_idx, across_idx, down_idx, set_label = set_entry

        make_and_save(base_idx, up_idx,     f'composite_{set_label}_up')
        make_and_save(base_idx, across_idx, f'composite_{set_label}_across')
        make_and_save(base_idx, down_idx,   f'composite_{set_label}_down')

    # -----------------------------------------------------------------------
    # Write spec.xml
    # -----------------------------------------------------------------------
    _write_std_spec(out_dir, n_sprites, headers, composites)


def _write_std_spec(out_dir, n_sprites, headers, composites):
    with open(os.path.join(out_dir, 'spec.xml'), 'w') as f:
        f.write(f'<icn count="{n_sprites}">\n')
        for idx, hdr in enumerate(headers):
            f.write(
                f'  <sprite id="{idx}" file="{idx:04d}.png"'
                f' offsetX="{hdr["ox"]}" offsetY="{hdr["oy"]}"'
                f' width="{hdr["w"]}" height="{hdr["h"]}"/>\n'
            )
        if composites:
            f.write('  <!-- Composite attack frames (base + overlay) -->\n')
            for name in composites:
                f.write(f'  <composite file="{name}.png"/>\n')
        f.write('</icn>\n')


# ===========================================================================
# ATK decoder
# ===========================================================================

# ATK layout:
#   F0       : base frame (always shown)
#   F1–F4    : animation overlay frames (composited on top of F0)
#   F5–F9    : projectile frames (separate, exported individually)

def decode_atk(icn_data, palette, out_dir, stem):
    """
    Decode an ATK file:
      - Write individual frame PNGs (all frames including projectiles)
      - Write composite PNGs: base(F0) + each overlay(F1-F4)
      - Write spec.xml
    """
    if not PIL_AVAILABLE:
        return

    n_sprites, headers = _read_icn_headers(icn_data)
    if n_sprites == 0:
        return

    os.makedirs(out_dir, exist_ok=True)

    # Decode all sprites (keep all – projectiles may be small)
    sprites = {}
    for idx, hdr in enumerate(headers):
        is_mono = False
        if idx > 9:
            is_mono = True

        sprites[idx] = _decode_one_sprite(icn_data, hdr, palette, mono=is_mono)

    # -----------------------------------------------------------------------
    # Write individual frame PNGs
    # -----------------------------------------------------------------------
    for idx, img in sprites.items():
        if img is None:
            continue
        img.save(os.path.join(out_dir, f'{idx:04d}.png'))

    # -----------------------------------------------------------------------
    # Composite attack frames: F0 (base) + F1..F4 (overlays)
    # -----------------------------------------------------------------------
    composites = []
    base_img = sprites.get(0)
    base_hdr = headers[0] if headers else None

    if base_img is not None and base_hdr is not None:
        for overlay_idx in range(1, min(5, n_sprites)):
            over_img = sprites.get(overlay_idx)
            over_hdr = headers[overlay_idx] if overlay_idx < len(headers) else None
            if over_img is None or over_hdr is None:
                continue
            composite = _composite_sprites([(base_img, base_hdr),
                                            (over_img, over_hdr)])
            if composite:
                name = f'composite_atk_F{overlay_idx}'
                composite.save(os.path.join(out_dir, f'{name}.png'))
                composites.append(name)

    # -----------------------------------------------------------------------
    # Projectile frames: label them clearly
    # -----------------------------------------------------------------------
    proj_frames = []
    for proj_idx in range(5, min(10, n_sprites)):
        img = sprites.get(proj_idx)
        if img is not None:
            name = f'projectile_F{proj_idx}'
            img.save(os.path.join(out_dir, f'{name}.png'))
            proj_frames.append(name)

    # -----------------------------------------------------------------------
    # Write spec.xml
    # -----------------------------------------------------------------------
    with open(os.path.join(out_dir, 'spec.xml'), 'w') as f:
        f.write(f'<icn count="{n_sprites}">\n')
        for idx, hdr in enumerate(headers):
            role = ''
            if idx == 0:
                role = ' role="base"'
            elif 1 <= idx <= 4:
                role = ' role="overlay"'
            elif 5 <= idx <= 9:
                role = ' role="projectile"'
            f.write(
                f'  <sprite id="{idx}" file="{idx:04d}.png"'
                f' offsetX="{hdr["ox"]}" offsetY="{hdr["oy"]}"'
                f' width="{hdr["w"]}" height="{hdr["h"]}"'
                f'{role}/>\n'
            )
        if composites:
            f.write('  <!-- Composite attack frames (base F0 + overlay Fn) -->\n')
            for name in composites:
                f.write(f'  <composite file="{name}.png"/>\n')
        if proj_frames:
            f.write('  <!-- Projectile frames -->\n')
            for name in proj_frames:
                f.write(f'  <composite file="{name}.png" role="projectile"/>\n')
        f.write('</icn>\n')


# ===========================================================================
# Generic ICN sprite decoder (for ICN / WLK / WIP)
# ===========================================================================

# Global sprites indicate the entire sprite file should be monochromatic
GLOBAL_MONO_SPRITES = ["losewalk", "font", "smalfont", "radar", "shadow32"]
# Sub sprites indicate that only specific sprites should be monochromatic
SUB_MONO_SPRITES = {
    "swapbtn": [2], 
    "locators": [20],
    "catapult": [15, 16]
}

def decode_icn(icn_data, palette, out_dir):
    if not PIL_AVAILABLE:
        return
    if len(icn_data) < 6:
        raise ValueError("ICN file too small")

    n_sprites, headers = _read_icn_headers(icn_data)
    if n_sprites == 0:
        return

    os.makedirs(out_dir, exist_ok=True)

    sorted_dofs = sorted(set(h['dof'] for h in headers))

    def data_end(dof):
        for d in sorted_dofs:
            if d > dof:
                return 6 + d
        return len(icn_data)

    icn_name = Path(out_dir).stem
    ext = Path(out_dir).suffix.upper()
    is_global_mono = (icn_name in GLOBAL_MONO_SPRITES)

    for idx, hdr in enumerate(headers):
        sw, sh = hdr['w'], hdr['h']
        if sw == 0 or sh == 0:
            continue

        is_sub_mono = False
        if not SUB_MONO_SPRITES.get(icn_name) is None and idx in SUB_MONO_SPRITES[icn_name]:
            is_sub_mono = True

        if ext == ".WLK" and idx > 5:
            is_sub_mono = True

        sprite_is_mono = is_global_mono or is_sub_mono

        img = _decode_one_sprite(icn_data, hdr, palette, mono=sprite_is_mono)
        if img is not None:
            img.save(os.path.join(out_dir, f'{idx:04d}.png'))

    # Write spec.xml with offsets for reference
    with open(os.path.join(out_dir, 'spec.xml'), 'w') as f:
        f.write(f'<icn count="{n_sprites}">\n')
        for idx, hdr in enumerate(headers):
            f.write(
                f'  <sprite id="{idx}" file="{idx:04d}.png"'
                f' offsetX="{hdr["ox"]}" offsetY="{hdr["oy"]}"'
                f' width="{hdr["w"]}" height="{hdr["h"]}"/>\n'
            )
        f.write('</icn>\n')


# ===========================================================================
# TIL tile decoder
#
# u16 n_tiles, u16 width, u16 height
# then n_tiles * width*height bytes of palette indices
# ===========================================================================

def decode_til(til_data, palette, out_dir):
    if not PIL_AVAILABLE:
        return
    if len(til_data) < 6:
        return
    pos = 0
    n_tiles, pos = u16(til_data, pos)
    width,   pos = u16(til_data, pos)
    height,  pos = u16(til_data, pos)
    if width == 0 or height == 0:
        return
    os.makedirs(out_dir, exist_ok=True)
    tile_sz = width * height
    for i in range(n_tiles):
        chunk = til_data[pos : pos + tile_sz]; pos += tile_sz
        img = Image.new('RGB', (width, height))
        img.putdata([palette[b] for b in chunk])
        img.save(os.path.join(out_dir, f'{i:04d}.png'))


# ===========================================================================
# BMP decoder (HoMM palette-indexed, NOT standard Windows BMP)
#
# Header: 0x21 0x00, u16 width, u16 height
# Data:   width*height palette indices (values 0, 1, or 2)
# ===========================================================================

def decode_homm_bmp(bmp_data, palette, out_path):
    if not PIL_AVAILABLE:
        return
    if len(bmp_data) < 6:
        return
    pos = 0
    magic_hi = bmp_data[pos]; magic_lo = bmp_data[pos+1]; pos += 2
    if magic_hi != 0x21 or magic_lo != 0x00:
        print(f"  WARNING: unexpected BMP magic 0x{magic_hi:02X} 0x{magic_lo:02X}")
    width,  pos = u16(bmp_data, pos)
    height, pos = u16(bmp_data, pos)
    if width == 0 or height == 0:
        return
    raw = bmp_data[pos : pos + width * height]
    img = Image.new('RGB', (width, height))
    img.putdata([palette[b] for b in raw])
    img.save(out_path)


# ===========================================================================
# BKG decoder (battle background sky strip)
#
# Header: u16 magic (0x0021), u16 width, u16 height
# Data:   width*height palette indices (RGB, no transparency)
#
# Identical structure to the HoMM BMP format. The 0x0021 magic word is
# stored little-endian so bytes 0-1 are 0x21 0x00.
# ===========================================================================

def decode_bkg(bkg_data, palette, out_path):
    if not PIL_AVAILABLE:
        return
    if len(bkg_data) < 6:
        return
    width,  _ = u16(bkg_data, 2)
    height, _ = u16(bkg_data, 4)
    if width == 0 or height == 0:
        return
    raw = bkg_data[6 : 6 + width * height]
    img = Image.new('RGB', (width, height))
    img.putdata([palette[b] for b in raw])
    img.save(out_path)



# ===========================================================================
# 82M decoder (raw PCM audio -> WAV)
#
# HoMM1 .82m files are raw PCM with no header.
# Based on observed files: 11025 Hz, mono, 16-bit signed PCM.
#
# The homm_82m_converter.py companion script notes that some files carry an
# optional "82M " magic header (4 bytes magic + u32 sample_rate + u16 channels
# + u16 bits_per_sample), but HoMM1 AGG files appear to be headerless raw PCM.
# ===========================================================================

import wave

_82M_SAMPLE_RATE    = 11025
_82M_CHANNELS       = 1
_82M_BITS_PER_SAMPLE = 16

def decode_82m(raw_data, out_path):
    """
    Convert raw .82m PCM data to a standard WAV file.

    Tries to detect the optional "82M " header; if absent, uses the
    HoMM1 defaults (11025 Hz, mono, 16-bit signed PCM).
    """
    offset = 0
    sr   = _82M_SAMPLE_RATE
    ch   = _82M_CHANNELS
    bps  = _82M_BITS_PER_SAMPLE

    if len(raw_data) >= 12 and raw_data[:4] == b'82M ':
        sr     = struct.unpack_from('<I', raw_data, 4)[0]
        ch     = struct.unpack_from('<H', raw_data, 8)[0]
        bps    = struct.unpack_from('<H', raw_data, 10)[0]
        offset = 12

    pcm = raw_data[offset:]
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(ch)
        wf.setsampwidth(bps // 8)
        wf.setframerate(sr)
        wf.writeframes(pcm)


# ===========================================================================
# Main extraction
# ===========================================================================

def extract(agg_path):
    agg_path = Path(agg_path)
    if not agg_path.exists():
        print(f"ERROR: file not found: {agg_path}")
        sys.exit(1)

    data = agg_path.read_bytes()
    out_root = Path(agg_path.stem)
    out_root.mkdir(exist_ok=True)

    print(f"Reading {agg_path} ...")
    records = parse_agg(data)

    # --- Load palette first (needed for all image decoding) ---
    palette = None
    for r in records:
        if r['name'].upper().endswith('.PAL'):
            print(f"Loading palette from '{r['name']}' ...")
            palette = load_palette(r['data'])
            swatch = out_root / 'palette_swatch.png'
            save_palette_swatch(palette, swatch)
            print(f"  palette swatch -> {swatch}")
            break  # use first PAL found (both are identical in HoMM1)

    if palette is None:
        print("WARNING: No .PAL file found - using greyscale fallback.")
        palette = [(i, i, i) for i in range(256)]

    # --- Extract all files ---
    for r in records:
        name  = r['name']
        fdata = r['data']

        if not name:
            continue

        ext      = Path(name).suffix.upper() if '.' in name else ''
        stem     = Path(name).stem
        out_path = out_root / name

        if ext == '.ICN':
            sprite_dir = out_root / stem
            print(f"  ICN  {name}  ->  {sprite_dir}/")
            try:
                decode_icn(fdata, palette, str(sprite_dir))
            except Exception as e:
                import traceback
                print(f"    ERROR: {e}")
                traceback.print_exc()

        elif ext in ('.WLK', '.WIP'):
            # Walk cycle and death animations – plain ICN decoding is fine.
            sprite_dir = out_root / (stem + ext.lower())
            print(f"  {ext[1:]}  {name}  ->  {sprite_dir}/")
            try:
                decode_icn(fdata, palette, str(sprite_dir))
            except Exception as e:
                import traceback
                print(f"    ERROR: {e}")
                traceback.print_exc()

        elif ext == '.STD':
            # Standing/idle + attack animation with base+overlay compositing.
            sprite_dir = out_root / (stem + ext.lower())
            print(f"  STD  {name}  ->  {sprite_dir}/")
            try:
                decode_std(fdata, palette, str(sprite_dir), stem)
            except Exception as e:
                import traceback
                print(f"    ERROR: {e}")
                traceback.print_exc()

        elif ext == '.ATK':
            # Attack animation with base+overlay compositing + projectile frames.
            sprite_dir = out_root / (stem + ext.lower())
            print(f"  ATK  {name}  ->  {sprite_dir}/")
            try:
                decode_atk(fdata, palette, str(sprite_dir), stem)
            except Exception as e:
                import traceback
                print(f"    ERROR: {e}")
                traceback.print_exc()

        elif ext == '.TIL':
            tile_dir = out_root / stem
            print(f"  TIL  {name}  ->  {tile_dir}/")
            try:
                decode_til(fdata, palette, str(tile_dir))
            except Exception as e:
                print(f"    ERROR: {e}")

        elif ext == '.BMP':
            png_path = out_root / (stem + '.png')
            print(f"  BMP  {name}  ->  {png_path}")
            try:
                decode_homm_bmp(fdata, palette, str(png_path))
            except Exception as e:
                print(f"    ERROR: {e}")

        elif ext == '.BKG':
            # Battle background sky strip – single palette-indexed image.
            png_path = out_root / (stem + '_bkg.png')
            print(f"  BKG  {name}  ->  {png_path}")
            try:
                decode_bkg(fdata, palette, str(png_path))
            except Exception as e:
                print(f"    ERROR: {e}")

        elif ext in ('.OBJ', '.XTL'):
            # Battle-scene sprites using plain ICN encoding.
            # OBJ: decorative objects (trees, rocks, etc.) placed on hex tiles.
            # XTL: the hex tile shapes (full tile, edge variants F1-F4, etc.)
            sprite_dir = out_root / (stem + ext.lower())
            print(f"  {ext[1:]}  {name}  ->  {sprite_dir}/")
            try:
                decode_icn(fdata, palette, str(sprite_dir))
            except Exception as e:
                import traceback
                print(f"    ERROR: {e}")
                traceback.print_exc()

        elif ext == '.82M':
            # Raw PCM audio – convert to WAV for standard playback.
            wav_path = out_root / (stem + '.wav')
            print(f"  SND  {name}  ->  {wav_path}")
            try:
                decode_82m(fdata, str(wav_path))
            except Exception as e:
                print(f"    ERROR: {e}  (saving raw instead)")
                out_path.write_bytes(fdata)

        elif ext == '.PAL':
            print(f"  PAL  {name}  ->  {out_path}")
            out_path.write_bytes(fdata)

        else:
            print(f"  RAW  {name}  ->  {out_path}")
            out_path.write_bytes(fdata)

    print(f"\nDone. All files extracted to '{out_root}/'")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Extract and decode Heroes of Might and Magic I AGG archives '
                    '(including WLK/STD/WIP/ATK animation sprites with compositing).')
    parser.add_argument('agg_file', help='Path to heroes.agg')
    args = parser.parse_args()
    extract(args.agg_file)
