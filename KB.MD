# Heroes of Might and Magic I — KB Demo AGG Extractor

A Python tool for extracting and decoding all asset files from the `KB.AGG` archive found in the **CES Demo** version of Heroes of Might and Magic I.

## What is KB.AGG?

`KB.AGG` is the asset archive from an early demo of HoMM1 distributed at the Consumer Electronics Show, predating the retail release. It uses a different AGG format from the retail `HEROES.AGG`: entries do not carry embedded filenames, so `kb_extract.py` uses a hand-built name table derived by cross-referencing retail file sizes and positional ordering to identify as many entries as possible.

The demo contains 626 entries. Most are earlier versions of retail assets — different art, different color choices, different animation frames — making it a fascinating snapshot of the game's development. A number of entries have no retail equivalent at all and appear to be pre-release-only content.

## Requirements

```bash
pip install Pillow
```

## Usage

```bash
python kb_extract.py kb.agg
```

```bash
python kb_extract.py kb.agg --palette 8 --survey
```

- `--palette INDEX` — palette entry index to use for image decoding (default: `8`, which is `kb.pal`)
- `--survey` — also print structural analysis to stdout for every UNKNOWN file

All files are extracted into a `kb/` subdirectory. Each entry is named using the pattern `{index:04d}_{id}_{size}_{name}`, for example:

```
kb/
├── 0008_xxxx_768_kb.pal_swatch.png
├── 0015_xxxx_nnnn_redback.bmp.png
├── 0052_xxxx_nnnn_peasant.std/
│   ├── 0001.png
│   ├── composite_atk_up.png
│   └── spec.xml
├── 0474_xxxx_nnnn_wsnd00.wav
└── _index.tsv
```

A `_index.tsv` master index is written listing every entry's index, ID, size, detected type, known name, and notes.

---

## Notable Pre-Release Assets

The following entries are particularly interesting for what they reveal about the game's development. Index numbers refer to the `{index:04d}` prefix in the output folder names.

### UI and Screens

**0015 — `redback.bmp`**
The button set for the main screen. Notably includes a *Quit to DOS* button, which was removed from the retail release.

**0147 — `bord.bmp`**
The adventure map border. Features different hero and castle locator art, different adventure map buttons, and a miniature HoMM logo that does not appear in the retail version.

**0148 — `heroes.bmp`**
A vintage New World Computing logo screen.

**0149 — `heroscrn.bmp`**
A bare title background screen without the overlaid title graphics.

**0184 — `advbtns.icn`**
The adventure map button icons. The kingdom overview button has notably different art compared to the retail version.

**0429 — `cpanel.bmp`**
The combat panel background. Like `redback.bmp`, this version includes a *Quit to DOS* option not present in the retail game.

**0611 — `titlebak.bmp`**
A raw title screen background image.

**0612 — `titleext.bmp`**
Additional title screen overlay graphics, used in combination with `titlebak.bmp`.

### Title Screen Animations

These ICN files contain the animated elements composited over the title screen — content that was handled differently or removed in the retail release.

**0613–0619 — `orngtent.icn` through `whitetnt.icn`**
Tent animation frames in seven color variants for the title screen.

**0620 — `introcas.icn`**
Castle banner animation frames for the title screen.

**0621 — `introcre.icn`**
Creature cheering animation frames for the title screen.

### Standing Heroes

**0046 — `herostnd.icn`**
Before the tent system, heroes waiting at the edge of the adventure map were represented as standing figures. This ICN contains those standing hero sprites, which have no equivalent in the final retail game.

### Kingdom Overview Screen Variants

**0331–0334 — `red-overmain.bmp`, `yellow-overmain.bmp`, `congrats.bmp`, `credits.bmp`**
Four colored kingdom overview screen combinations. In the final game these backgrounds were merged into a single unified screen; the demo kept them as separate colored variants.

### Adventure Map Locators

**0319 — `locators.icn`**
The blank hero locator icons used on the adventure map sidebar. These have different art from the retail version.

### Town Buildings

**0206 — `farmcast.icn`**
The Knight town castle building. In this early version the castle flags are **purple**, whereas in the retail game they are red.

**0209 — `farm_d1.icn`**
The Knight town archery range. The flags here are **red**, whereas in the retail game they are purple. The flag colors for these two buildings were swapped between the demo and release.

**0246 — `plns_d4.icn`**
The Plains town troll bridge building. In this version the **water beneath the bridge is animated** — the water tiles cycle through palette frames. This animation was not carried over to the retail release.

### Mountain Town Buildings

The mountain town creature dwellings use different assignments in the demo compared to retail:

| Index | File | Demo contents | Retail equivalent |
|---|---|---|---|
| 0261 | `mtn_d1.icn` | Griffin dwelling | Gargoyle dwelling |
| 0262 | `mtn_d2.icn` | Gargoyle dwelling | Griffin dwelling |
| 0263 | `mtn_d3.icn` | Animated maze (leaf animation) | Standard maze |
| 0264 | `mtn_d4.icn` | Different swamp structure with trees | Standard swamp |

The griffin and gargoyle dwellings are swapped relative to retail, and the maze building has a leaf animation that was removed. Entry 0264 is an entirely different swamp structure.

### Catapult

**0045 — `catapult.icn`**
Earlier catapult animation graphics, different from the retail siege weapon art.

---

## UNKNOWN Entries

Most of the entries labelled `UNKNOWN` in the output are `.bin` data files that define event window layouts — dialog boxes, army management screens, and similar UI components. In the retail game these were named things like `advwind.bin` and contained positional layout data referencing sprites from `buybuild.icn` and similar ICN files. The KB demo versions have not yet been matched to retail filenames, so they remain unidentified in the name table and are saved with a `_survey.txt` structural analysis inside their folder to assist further reverse engineering.

---

## Decoding

`kb_extract.py` applies the same decoding pipeline as the retail extractor:

- **ICN, WLK, WIP** — decoded as sprite sheets; each frame saved as a numbered PNG with a `spec.xml` offset metadata file.
- **STD** — standing/idle and attack frames decoded with base+overlay compositing. Attack direction composites (`composite_atk_up.png`, `composite_atk_across.png`, `composite_atk_down.png`) are generated for each creature. Extended creatures (dragon, cyclops, phoenix) produce three composite sets.
- **ATK** — ranged attack frames decoded with base+overlay compositing. Projectile frames (F5–F9) are extracted individually and labelled `projectile_F5.png` etc.
- **TIL** — tile sheets decoded to numbered PNGs.
- **BMP** — HoMM palette-indexed images (not standard Windows BMP format) decoded to PNG.
- **82M** — raw PCM audio converted to standard WAV files (11025 Hz, mono, 16-bit by default). The optional `"82M "` header is detected and used when present.
- **PAL** — raw palette saved as `.bin`; a `palette_swatch.png` color strip is generated for inspection.
- **Everything else** — saved verbatim as `_raw.bin` inside a survey folder.

---

## Credits

Written by Andrew G. Stevens with assistance from Claude Sonnet 4.6.

## License

This code is released under the Apache License, Version 2.0.
