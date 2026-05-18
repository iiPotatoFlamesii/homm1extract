#!/usr/bin/env python3
"""
Heroes of Might and Magic I - KB Demo AGG extractor (named/verified version).

Extracts all 626 entries from KB.AGG using a hand-built name table derived
by cross-referencing the retail HEROES.AGG by file size and positional ordering.

Output folder naming
--------------------
Every entry is extracted to a folder (or file) named:

    {index:04d}_{id}_{size}_{name}

e.g.  0010_903A_58428_poof.icn/
      0150_E844_126982_ground32.til/
      0166_D61E_31110_demo.map

For entries with no confirmed name the name portion is left as UNKNOWN, so
they sort cleanly and are easy to spot:

    0005_BB43_3013_UNKNOWN/

Each UNKNOWN entry also gets a  _survey.txt  file inside its folder with a
hex dump and structural analysis to help with further reverse engineering.

The master index (all 626 entries) is written to  kb/_index.tsv  with columns:
    index, kb_id, size, detected_type, known_name, observations

Fill in the observations column as you verify files.

Decoding summary
----------------
  ICN              -> PNG sprites (RGBA, with transparency)
  WLK, WIP         -> PNG sprites (walk/death animations, same ICN encoding)
  STD              -> PNG sprites + composite attack frames (base+overlay)
                      using spec.xml offsets; shadow composites alongside body
  ATK              -> PNG sprites + composite attack frames (base+overlay)
                      + projectile frames (F5-F9) extracted individually
  TIL              -> PNG tiles
  BMP              -> PNG images (HoMM palette-indexed format, NOT standard BMP)
  PAL              -> raw palette saved + palette_swatch.png for inspection
  82M              -> WAV (PCM header detection; defaults to 11025 Hz mono 16-bit)
  everything else  -> saved verbatim in _raw.bin

Usage
-----
    pip install Pillow
    python kb_extract.py kb.agg [--palette INDEX] [--survey]

    --palette INDEX   Palette entry index to use for image decoding (default 8)
    --survey          Also print survey info to stdout for every UNKNOWN file


## STD frame layout (standard 18-frame creatures)

  F0  : noise – skip
  F1  : standing body
  F2  : death body
  F3  : attack frame 1 body
  F4  : attack frame 2 body
  F5  : base body (full pose used as bottom layer for F6-F8)
          For flying creatures (gargoyle, griffin, ghost, wolf) this is a
          small shadow-anchor patch rather than a full body sprite.
  F6  : attack-up overlay    (composited on top of F5)
  F7  : attack-across overlay
  F8  : attack-down overlay
  F9  : 1x1 sentinel (ignored)
  F10 : shadow for F1
  ...
  F17 : shadow for F8 / attack-down

  Extended creatures (dragon, cyclops, phoenix) have 33 frames with three
  overlay sets (F6-F8, F9-F11, F12-F14).

## ATK frame layout

  F0     : base frame
  F1-F4  : animation overlay frames (composited on F0)
  F5-F9  : projectile frames (exported individually)

## Credits

Written by Andrew G. Stevens with assistance from Claude Sonnet 4.6.
Apache License 2.0.
"""

import struct
import os
import sys
import argparse
import wave
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not found. Images will not be decoded.")
    print("         Install with: pip install Pillow\n")


# ===========================================================================
# Name table
#
# Built by cross-referencing retail HEROES.AGG file sizes and positional
# ordering of grouped files (creature animations, portraits, town data, etc).
# Entries marked UNKNOWN have no confirmed retail equivalent or positional match.
# The 'observations' field is intentionally blank — fill it in as you verify.
#
# Format: index -> (confirmed_name_or_None, observations)
# ===========================================================================

NAME_TABLE = {
    # idx : (name,           observations)
    0:   (None,              '17 bytes; likely bigfont.fnt or smalfont.fnt (size ambiguous)'),
    1:   (None,              '17 bytes; likely bigfont.fnt or smalfont.fnt (size ambiguous)'),
    2:   (None,              '79 bytes; no retail size match'),
    3:   (None,              '87 bytes; no retail size match'),
    4:   ('spelmous.mse',    ''),
    5:   ('advmous.icn',     'Manually identified'),
    6:   ('cmbtmous.icn',    'Manually identified'),
    7:   ('spells.icn',      'Manually identified; size differs from retail'),
    8:   ('kb.pal',          'Primary overworld palette'),
    9:   ('combat.pal',      'Combat palette'),
    10:  ('poof.icn',        ''),
    11:  ('textbar.icn',     ''),
    12:  (None,              '4938-byte ICN; near poof/textbar block — UI element?'),
    13:  (None,              '3940-byte ICN; near poof/textbar block — UI element?'),
    14:  (None,              '238 bytes; size matches several small .bin files'),
    15:  ('redback.bmp',     ''),
    16:  ('btnmain.icn',     'Manually identified; size differs from retail'),
    17:  (None,              '1302 bytes; no retail size match'),
    18:  ('recruit.bmp',     'Manually identified; 640x230 pre-release recruit screen'),
    19:  ('newgame.icn',     'Manually identified; size differs from retail'),
    # Battle tiles (XTL stored as ICN in KB, positional ordering matches retail)
    20:  ('boat.xtl',        'Battle tile; stored as ICN'),
    21:  ('grass.xtl',       'Battle tile; stored as ICN'),
    22:  ('dgrass.xtl',      'Battle tile; stored as ICN'),
    23:  ('dirt.xtl',        'Battle tile; stored as ICN'),
    24:  ('snow.xtl',        'Battle tile; stored as ICN'),
    25:  ('swamp.xtl',       'Battle tile; stored as ICN'),
    26:  ('desert.xtl',      'Battle tile; stored as ICN'),
    27:  ('lava.xtl',        'Battle tile; stored as ICN'),
    28:  ('grass.obj',       'Manually identified'),
    29:  ('dgrass.obj',      'Manually identified'),
    30:  ('snow.obj',        'Manually identified'),
    31:  ('swamp.obj',       'Manually identified'),
    32:  ('lava.obj',        'Manually identified'),
    33:  ('desert.obj',      'Manually identified'),
    # Battle backgrounds (positional ordering matches retail)
    34:  ('boat.bkg',        'Battle background'),
    35:  ('frstwgrs.bkg',    'Battle background'),
    36:  ('mtnwgrsf.bkg',    'Battle background'),
    37:  ('snowfrst.bkg',    'Battle background'),
    38:  ('snowmtnf.bkg',    'Battle background'),
    39:  ('swamp.bkg',       'Battle background'),
    40:  ('lava.bkg',        'Battle background'),
    41:  ('desert.bkg',      'Battle background'),
    42:  ('frstwdrt.bkg',    'Battle background'),
    43:  ('mtnwdrtf.bkg',    'Battle background; gravyard.bkg absent — likely added post-demo'),
    44:  ('selector.icn',    ''),
    45:  ('catapult.icn',    'Manually identified; size differs from retail'),
    46:  ('herostnd.icn',    'Manually identified; no retail equivalent'),
    47:  ('castle00.icn',    ''),
    48:  ('castle01.icn',    ''),
    49:  ('castle02.icn',    ''),
    50:  ('castle03.icn',    ''),
    51:  ('cloud.icn',       ''),
    # Creature STD/WLK/ATK animations — positional ordering matches retail exactly.
    # Sizes differ from retail (earlier art); names confirmed by sequence position.
    52:  ('peasant.std',     'Positional match; size differs from retail'),
    53:  ('peasant.wlk',     'Positional match; size differs from retail'),
    54:  ('archer.std',      'Positional match; size differs from retail'),
    55:  ('archer.wlk',      'Positional match; size differs from retail'),
    56:  ('archer.atk',      'Positional match; size differs from retail'),
    57:  ('pikeman.std',     'Positional match; size differs from retail'),
    58:  ('pikeman.wlk',     'Positional match; size differs from retail'),
    59:  ('swrdsman.std',    'Positional match; size differs from retail'),
    60:  ('swrdsman.wlk',    'Positional match; size differs from retail'),
    61:  ('cavalry.std',     'Positional match; size differs from retail'),
    62:  ('cavalry.wlk',     'Positional match; size differs from retail'),
    63:  ('paladin.std',     'Positional match; size differs from retail'),
    64:  ('paladin.wlk',     'Positional match; size differs from retail'),
    65:  ('goblin.std',      'Positional match; size differs from retail'),
    66:  ('goblin.wlk',      'Positional match; size differs from retail'),
    67:  ('orc.std',         'Positional match; size differs from retail'),
    68:  ('orc.wlk',         'Positional match; size differs from retail'),
    69:  ('orc.atk',         'Positional match; size differs from retail'),
    70:  ('wolf.std',        'Positional match; size differs from retail'),
    71:  ('wolf.wlk',        'Positional match; size differs from retail'),
    72:  ('ogre.std',        'Positional match; size differs from retail'),
    73:  ('ogre.wlk',        'Positional match; size differs from retail'),
    74:  ('troll.std',       'Positional match; size differs from retail'),
    75:  ('troll.wlk',       'Positional match; size differs from retail'),
    76:  ('troll.atk',       'Positional match; size differs from retail'),
    77:  ('cyclops.std',     'Positional match; size differs from retail'),
    78:  ('cyclops.wlk',     'Positional match; size differs from retail'),
    79:  ('sprite.std',      'Positional match; size differs from retail'),
    80:  ('sprite.wlk',      'Positional match; size differs from retail'),
    81:  ('dwarf.std',       'Positional match; size differs from retail'),
    82:  ('dwarf.wlk',       'Positional match; size differs from retail'),
    83:  ('druid.std',       'Positional match; size differs from retail'),
    84:  ('druid.wlk',       'Positional match; size differs from retail'),
    85:  ('druid.atk',       'Positional match; size differs from retail'),
    86:  ('elf.std',         'Positional match; size differs from retail'),
    87:  ('elf.wlk',         'Positional match; size differs from retail'),
    88:  ('elf.atk',         'Positional match; size differs from retail'),
    89:  ('unicorn.std',     'Positional match; size differs from retail'),
    90:  ('unicorn.wlk',     'Positional match; size differs from retail'),
    91:  ('phoenix.std',     'Positional match; size differs from retail'),
    92:  ('phoenix.wlk',     'Positional match; size differs from retail'),
    93:  ('centaur.std',     'Positional match; size differs from retail'),
    94:  ('centaur.wlk',     'Positional match; size differs from retail'),
    95:  ('centaur.atk',     'Positional match; size differs from retail'),
    96:  ('gargoyle.std',    'Positional match; size differs from retail'),
    97:  ('gargoyle.wlk',    'Positional match; size differs from retail'),
    98:  ('griffin.std',     'Positional match; size differs from retail'),
    99:  ('griffin.wlk',     'Positional match; size differs from retail'),
    100: ('minotaur.std',    'Positional match; size differs from retail'),
    101: ('minotaur.wlk',    'Positional match; size differs from retail'),
    102: ('hydra.std',       'Positional match; size differs from retail'),
    103: ('hydra.wlk',       'Positional match; size differs from retail'),
    104: ('dragon.std',      'Positional match; size differs from retail'),
    105: ('dragon.wlk',      'Positional match; size differs from retail'),
    106: ('rogue.std',       'Positional match; size differs from retail'),
    107: ('rogue.wlk',       'Positional match; size differs from retail'),
    108: ('nomad.std',       'Positional match; size differs from retail'),
    109: ('nomad.wlk',       'Positional match; size differs from retail'),
    110: ('ghost.std',       'Positional match; size differs from retail'),
    111: ('ghost.wlk',       'Positional match; size differs from retail'),
    112: ('genie.std',       'Positional match; size differs from retail'),
    113: ('genie.wlk',       'Positional match; size differs from retail'),
    # 28 x 19-byte mystery files — no retail size match.
    # Retail mouse files: advmice.mse=17b, cmbtmous.mse=?, spelmous.mse=255b.
    # These 28 files may be per-cursor hotspot records or split mouse data.
    114: (None, '19 bytes; one of 28 identical-size mystery files (114-141); possibly cursor data'),
    115: (None, '19 bytes; see index 114'),
    116: (None, '19 bytes; see index 114'),
    117: (None, '19 bytes; see index 114'),
    118: (None, '19 bytes; see index 114'),
    119: (None, '19 bytes; see index 114'),
    120: (None, '19 bytes; see index 114'),
    121: (None, '19 bytes; see index 114'),
    122: (None, '19 bytes; see index 114'),
    123: (None, '19 bytes; see index 114'),
    124: (None, '19 bytes; see index 114'),
    125: (None, '19 bytes; see index 114'),
    126: (None, '19 bytes; see index 114'),
    127: (None, '19 bytes; see index 114'),
    128: (None, '19 bytes; see index 114'),
    129: (None, '19 bytes; see index 114'),
    130: (None, '19 bytes; see index 114'),
    131: (None, '19 bytes; see index 114'),
    132: (None, '19 bytes; see index 114'),
    133: (None, '19 bytes; see index 114'),
    134: (None, '19 bytes; see index 114'),
    135: (None, '19 bytes; see index 114'),
    136: (None, '19 bytes; see index 114'),
    137: (None, '19 bytes; see index 114'),
    138: (None, '19 bytes; see index 114'),
    139: (None, '19 bytes; see index 114'),
    140: (None, '19 bytes; see index 114'),
    141: (None, '19 bytes; see index 114'),
    142: ('boulder.icn',     ''),
    143: ('viewgen.icn',     'Manually identified; size differs from retail'),
    144: ('viewarmy.icn',    ''),
    145: ('vgenback.icn',    ''),
    146: ('book.icn',        'Manually identified; size differs from retail'),
    # Full-screen BMPs (307206 = 640x480 + 6-byte header).
    # Retail has 6 unique files; KB has 10 slots — 4 are pre-release art not in retail.
    # First three match retail ordering; positions 311, 331-334, 611-612 are ambiguous.
    147: ('bord.bmp',        'Full-screen BMP; positional match'),
    148: ('heroes.bmp',      'Full-screen BMP; positional match'),
    149: ('heroscrn.bmp',    'Full-screen BMP; positional match'),
    150: ('ground32.til',    ''),
    151: ('object32.icn',    ''),
    152: ('ovrlay32.icn',    ''),
    153: ('kngt32.icn',      ''),
    154: ('barb32.icn',      'Size match; retail output listed as barb32.icn'),
    155: ('sorc32.icn',      ''),
    156: ('wrlk32.icn',      ''),
    157: ('b-flag32.icn',    'Size ties with g-flag32; positional match'),
    158: ('g-flag32.icn',    'Size ties with b-flag32; positional match'),
    159: ('r-flag32.icn',    ''),
    160: ('y-flag32.icn',    ''),
    161: ('boat32.icn',      ''),
    162: ('b-bflg32.icn',    'All four bflg32 files share size; positional match'),
    163: ('g-bflg32.icn',    'All four bflg32 files share size; positional match'),
    164: ('r-bflg32.icn',    'All four bflg32 files share size; positional match'),
    165: ('y-bflg32.icn',    'All four bflg32 files share size; positional match'),
    166: ('demo.map',        ''),
    167: ('bluefire.icn',    ''),
    168: ('redfire.icn',     ''),
    169: ('electric.icn',    ''),
    170: ('physical.icn',    ''),
    171: ('elecfire.icn',    ''),
    172: ('reddeath.icn',    ''),
    173: ('magic01.icn',     ''),
    174: ('magic02.icn',     ''),
    175: ('magic03.icn',     ''),
    176: ('magic04.icn',     ''),
    177: ('magic05.icn',     ''),
    178: ('magic06.icn',     ''),
    179: ('magic07.icn',     ''),
    180: ('magic08.icn',     ''),
    181: ('fireball.icn',    ''),
    182: ('storm.icn',       ''),
    183: ('meteor.icn',      ''),
    184: ('advbtns.icn',     'Manually confirmed; size differs from retail (pre-release version)'),
    185: ('radar.icn',       ''),
    # TOD files — 27-byte data blocks, one per town building type.
    # Positional match: each TOD immediately precedes its matching ICN block.
    186: ('magegld.tod',     'Positional match'),
    187: ('thievesg.tod',    'Positional match'),
    188: ('tavern.tod',      'Positional match'),
    189: ('dock.tod',        'Positional match'),
    190: ('well.tod',        'Positional match'),
    191: ('magegld.icn',     ''),
    192: ('thievesg.icn',    ''),
    193: ('tavern.icn',      ''),
    194: ('dock.icn',        ''),
    195: ('well.icn',        ''),
    196: ('townbkg0.bmp',    'Positional match'),
    197: ('farmtent.tod',    'Positional match'),
    198: ('farmcast.tod',    'Positional match'),
    199: ('farm_d0.tod',     'Positional match'),
    200: ('farm_d1.tod',     'Positional match'),
    201: ('farm_d2.tod',     'Positional match'),
    202: ('farm_d3.tod',     'Positional match'),
    203: ('farm_d4.tod',     'Positional match'),
    204: ('farm_d5.tod',     'Positional match'),
    205: ('farmtent.icn',    ''),
    206: ('farmcast.icn',    'No retail size match; positional match'),
    207: ('farm_d0.icn',     ''),
    208: ('farm_d2.icn',     'Note: out of order vs filename; matches retail size'),
    209: ('farm_d1.icn',     'Note: out of order vs filename; no retail size match'),
    210: ('farm_d3.icn',     ''),
    211: ('farm_d4.icn',     ''),
    212: ('farm_d5.icn',     ''),
    213: ('townbkg1.bmp',    'Positional match'),
    214: ('frsttent.tod',    'Positional match'),
    215: ('frstcast.tod',    'Positional match'),
    216: ('frst_d0.tod',     'Positional match'),
    217: ('frst_d1.tod',     'Positional match'),
    218: ('frst_d2.tod',     'Positional match'),
    219: ('frst_d3.tod',     'Positional match'),
    220: ('frst_d4.tod',     'Positional match'),
    221: ('frst_d5.tod',     'Positional match'),
    222: ('frsttent.icn',    ''),
    223: ('frstcast.icn',    ''),
    224: ('frst_d0.icn',     ''),
    225: ('frst_d1.icn',     ''),
    226: ('frst_d2.icn',     ''),
    227: ('frst_d3.icn',     ''),
    228: ('frst_d4.icn',     ''),
    229: ('frst_d5.icn',     ''),
    230: ('townbkg2.bmp',    'Positional match'),
    231: ('plnstent.tod',    'Positional match'),
    232: ('plnscast.tod',    'Positional match'),
    233: ('plns_d0.tod',     'Positional match'),
    234: ('plns_d1.tod',     'Positional match'),
    235: ('plns_d2.tod',     'Positional match'),
    236: ('plns_d3.tod',     'Positional match'),
    237: ('plns_d4.tod',     'Positional match'),
    238: ('plns_d5.tod',     'Positional match'),
    239: ('plns_e0.tod',     'Positional match'),
    240: ('plnstent.icn',    'No retail size match; positional match'),
    241: ('plnscast.icn',    ''),
    242: ('plns_d0.icn',     ''),
    243: ('plns_d2.icn',     'Note: out of order vs filename; no retail size match'),
    244: ('plns_d1.icn',     'Note: out of order vs filename'),
    245: ('plns_d3.icn',     'No retail size match'),
    246: ('plns_d4.icn',     'No retail size match'),
    247: ('plns_d5.icn',     ''),
    248: ('plns_e0.icn',     ''),
    249: ('townbkg3.bmp',    'Positional match'),
    250: ('mtntent.tod',     'Positional match'),
    251: ('mtncast.tod',     'Positional match'),
    252: ('mtn_d0.tod',      'Positional match'),
    253: ('mtn_d1.tod',      'Positional match'),
    254: ('mtn_d2.tod',      'Positional match'),
    255: ('mtn_d3.tod',      'Positional match'),
    256: ('mtn_d4.tod',      'Positional match'),
    257: ('mtn_d5.tod',      'Positional match'),
    258: ('mtntent.icn',     ''),
    259: ('mtncast.icn',     ''),
    260: ('mtn_d0.icn',      ''),
    261: ('mtn_d1.icn',      'No retail size match'),
    262: ('mtn_d2.icn',      'No retail size match'),
    263: ('mtn_d3.icn',      'No retail size match'),
    264: ('mtn_d4.icn',      'No retail size match'),
    265: ('mtn_d5.icn',      ''),
    266: ('strip.icn',       ''),
    267: ('monsters.icn',    ''),
    268: ('treasury.icn',    ''),
    269: ('resource.icn',    'No retail size match; positional match'),
    270: ('townfix.icn',     ''),
    271: ('townname.icn',    ''),
    272: (None,              '591 bytes; between townname.icn and magewind.bin — town data?'),
    273: (None,              '1036 bytes; between townname.icn and magewind.bin — town data?'),
    274: ('magewind.bin',    ''),
    275: ('caslwind.bin',    ''),
    276: ('thiefwin.bin',    ''),
    277: ('wellwind.bin',    ''),
    278: (None,              '230 bytes; no retail size match'),
    279: (None,              '654 bytes; no retail size match'),
    280: ('buybuild.icn',    'Manually identified; size differs from retail'),
    281: ('recruit0.bin',    ''),
    282: ('recruit1.bin',    ''),
    283: ('stonebak.bmp',    ''),
    284: ('building.icn',    ''),
    285: ('system.icn',      'Manually identified; size differs from retail'),
    286: ('townwind.icn',    ''),
    287: ('obj32-00.icn',    ''),
    288: ('obj32-01.icn',    ''),
    289: ('obj32-02.icn',    ''),
    290: ('obj32-03.icn',    ''),
    291: ('obj32-04.icn',    ''),
    292: ('obj32-05.icn',    ''),
    293: ('obj32-06.icn',    ''),
    294: ('obj32-07.icn',    ''),
    295: ('mtn32.icn',       ''),
    296: ('tree32.icn',      ''),
    297: ('town32.icn',      ''),
    298: ('rsrc32.icn',      ''),
    299: ('mons32.icn',      ''),
    300: ('art32.icn',       'No retail size match; positional match'),
    301: ('flag32.icn',      ''),
    302: (None,              '381 bytes; no retail size match'),
    303: ('armywin.bin',     ''),
    304: ('tavwin.icn',      ''),
    305: (None,              '573 bytes; no retail size match'),
    306: (None,              '350 bytes; no retail size match'),
    307: ('shipwind.bin',    ''),
    308: ('rcrthero.bin',    ''),
    309: (None,              '2630 bytes; no retail size match'),
    310: ('heroscrn.icn',    'Manually identified; size differs from retail'),
    311: ('hiscore.bmp',     'Full-screen BMP; positional match'),
    312: ('townstrp.bin',    ''),
    313: ('artifact.icn',    ''),
    314: ('statbar.bin',     ''),
    315: ('spellwin.bin',    ''),
    316: (None,              '382 bytes; no retail size match'),
    317: (None,              '382 bytes; same size as index 316'),
    318: ('scroll.icn',      ''),
    319: ('locators.icn',    'Manually identified; size differs from retail'),
    320: (None,              '643 bytes; no retail size match'),
    321: (None,              '227 bytes; no retail size match'),
    322: ('qtown0.bin',      ''),
    323: ('qtown1.bin',      'Size ties with advmice.mse and campaign.bin; positional match'),
    324: ('qwikinfo.bin',    ''),
    325: ('qwikhero.bmp',    ''),
    326: ('qwiktown.bmp',    ''),
    327: ('qwikinfo.bmp',    ''),
    328: ('splitwin.bin',    ''),
    329: (None,              '488 bytes; no retail size match'),
    330: ('overview.icn',    ''),
    # Full-screen BMPs continued
    331: ('congrats.bmp',    'Full-screen BMP; positional match'),
    332: ('credits.bmp',     'Full-screen BMP; positional match'),
    333: ('red-overmain.bmp',    'Manually identified; pre-release overworld main screen variant'),
    334: ('yellow-overmain.bmp', 'Manually identified; pre-release overworld main screen variant'),
    335: (None,              '952 bytes; no retail size match'),
    336: ('buybook.bin',     ''),
    337: ('puzzle.icn',      ''),
    338: (None,              '391 bytes; one of a cluster of small UNKs (338-342)'),
    339: (None,              '392 bytes; one of a cluster of small UNKs (338-342)'),
    340: (None,              '390 bytes; one of a cluster of small UNKs (338-342)'),
    341: (None,              '390 bytes; one of a cluster of small UNKs (338-342)'),
    342: (None,              '388 bytes; one of a cluster of small UNKs (338-342)'),
    343: (None,              '626 bytes; one of a cluster of medium UNKs (343-347)'),
    344: (None,              '628 bytes; one of a cluster of medium UNKs (343-347)'),
    345: (None,              '624 bytes; one of a cluster of medium UNKs (343-347)'),
    346: (None,              '624 bytes; one of a cluster of medium UNKs (343-347)'),
    347: (None,              '620 bytes; one of a cluster of medium UNKs (343-347)'),
    348: (None,              '322 bytes; no retail size match'),
    349: ('cmbtwin.bin',     ''),
    350: (None,              '333 bytes; one of a cluster (350-353) — combat window data?'),
    351: (None,              '336 bytes; one of a cluster (350-353) — combat window data?'),
    352: (None,              '342 bytes; one of a cluster (350-353) — combat window data?'),
    353: (None,              '315 bytes; one of a cluster (350-353) — combat window data?'),
    354: (None,              '2449 bytes; no retail size match'),
    355: ('swapwin.bmp',     ''),
    356: ('swapbtn.icn',     ''),
    357: ('tree6.icn',       ''),
    358: ('mtn6.icn',        ''),
    359: ('town6.icn',       ''),
    360: ('flag6.icn',       ''),
    361: ('ground6.icn',     ''),
    362: (None,              '806 bytes; no retail size match'),
    363: ('request.icn',     ''),
    364: ('request.bmp',     'Manually identified; pre-release request screen'),
    # Hero portraits — 56 slots (36 port + 20 crst), positional ordering matches retail
    365: ('port0000.icn',    'Positional match'),
    366: ('port0001.icn',    'Positional match'),
    367: ('port0002.icn',    'Positional match'),
    368: ('port0003.icn',    'Positional match'),
    369: ('port0004.icn',    'Positional match'),
    370: ('port0005.icn',    'Positional match'),
    371: ('port0006.icn',    'Positional match'),
    372: ('port0007.icn',    'Positional match'),
    373: ('port0008.icn',    'Positional match'),
    374: ('port0009.icn',    'Positional match'),
    375: ('port0010.icn',    'Positional match'),
    376: ('port0011.icn',    'Positional match'),
    377: ('port0012.icn',    'Positional match'),
    378: ('port0013.icn',    'Positional match'),
    379: ('port0014.icn',    'Positional match'),
    380: ('port0015.icn',    'Positional match'),
    381: ('port0016.icn',    'Positional match'),
    382: ('port0017.icn',    'Positional match'),
    383: ('port0018.icn',    'Positional match'),
    384: ('port0019.icn',    'Positional match'),
    385: ('port0020.icn',    'Positional match'),
    386: ('port0021.icn',    'Positional match'),
    387: ('port0022.icn',    'Positional match'),
    388: ('port0023.icn',    'Positional match'),
    389: ('port0024.icn',    'Positional match'),
    390: ('port0025.icn',    'Positional match'),
    391: ('port0026.icn',    'Positional match'),
    392: ('port0027.icn',    'Positional match'),
    393: ('port0028.icn',    'Positional match'),
    394: ('port0029.icn',    'Positional match'),
    395: ('port0030.icn',    'Positional match'),
    396: ('port0031.icn',    'Positional match'),
    397: ('port0032.icn',    'Positional match'),
    398: ('port0033.icn',    'Positional match'),
    399: ('port0034.icn',    'Positional match'),
    400: ('port0035.icn',    'Positional match'),
    401: ('crst0000.icn',    'Positional match'),
    402: ('crst0001.icn',    'Positional match'),
    403: ('crst0002.icn',    'Positional match'),
    404: ('crst0003.icn',    'Positional match'),
    405: ('crst0004.icn',    'Positional match'),
    406: ('crst0005.icn',    'Positional match'),
    407: ('crst0006.icn',    'Positional match'),
    408: ('crst0007.icn',    'Positional match'),
    409: ('crst0008.icn',    'Positional match'),
    410: ('crst0009.icn',    'Positional match'),
    411: ('crst0010.icn',    'Positional match'),
    412: ('crst0011.icn',    'Positional match'),
    413: ('crst0012.icn',    'Positional match'),
    414: ('crst0013.icn',    'Positional match'),
    415: ('crst0014.icn',    'Positional match'),
    416: ('crst0015.icn',    'Positional match'),
    417: ('crst0016.icn',    'Positional match'),
    418: ('crst0017.icn',    'Positional match'),
    419: ('crst0018.icn',    'Positional match'),
    420: ('crst0019.icn',    'Positional match'),
    421: ('surrendr.bin',    ''),
    422: ('surrendr.bmp',    ''),
    423: ('surrendr.icn',    ''),
    424: ('recruit.bmp',     ''),
    425: ('recruit.icn',     ''),
    426: ('artfx.icn',       ''),
    427: ('bigbar.icn',      ''),
    428: (None,              '571 bytes; no retail size match'),
    429: ('cpanel.bmp',      'Manually identified; pre-release combat panel background'),
    430: ('cpanel.icn',      'Manually identified; size differs from retail'),
    431: (None,              '402 bytes; no retail size match'),
    # Creature WIP (death) animations — positional ordering matches retail exactly
    432: ('peasant.wip',     'Positional match; size matches retail'),
    433: ('archer.wip',      'Positional match; size differs from retail'),
    434: ('pikeman.wip',     'Positional match; size matches retail'),
    435: ('swrdsman.wip',    'Positional match; size matches retail'),
    436: ('cavalry.wip',     'Positional match; size differs from retail'),
    437: ('paladin.wip',     'Positional match; size matches retail'),
    438: ('goblin.wip',      'Positional match; size differs from retail'),
    439: ('orc.wip',         'Positional match; size differs from retail'),
    440: ('wolf.wip',        'Positional match; size differs from retail'),
    441: ('troll.wip',       'Positional match; size matches retail'),
    442: ('cyclops.wip',     'Positional match; size matches retail'),
    443: ('druid.wip',       'Positional match; size matches retail'),
    444: ('dwarf.wip',       'Positional match; size differs from retail'),
    445: ('elf.wip',         'Positional match; size differs from retail'),
    446: ('unicorn.wip',     'Positional match; size differs from retail'),
    447: ('centaur.wip',     'Positional match; size differs from retail'),
    448: ('minotaur.wip',    'Positional match; size differs from retail'),
    449: ('hydra.wip',       'Positional match; size differs from retail'),
    450: ('rogue.wip',       'Positional match; size differs from retail'),
    451: ('nomad.wip',       'Positional match; size matches retail'),
    452: ('ogre.wip',        'Positional match; size matches retail'),
    453: (None,              '294 bytes; no retail size match'),
    454: ('woodgrai.bmp',    'Manually identified; pre-release wood grain texture'),
    455: (None,              '4113-byte ICN; no retail size match'),
    456: (None,              '115 bytes; one of a cluster (456-462) — possibly view window data'),
    457: (None,              '114 bytes; one of a cluster (456-462)'),
    458: (None,              '118 bytes; one of a cluster (456-462)'),
    459: (None,              '118 bytes; one of a cluster (456-462)'),
    460: (None,              '114 bytes; one of a cluster (456-462)'),
    461: (None,              '115 bytes; one of a cluster (456-462)'),
    462: (None,              '114 bytes; one of a cluster (456-462)'),
    463: ('spheres.icn',     ''),
    464: ('letters.icn',     ''),
    465: ('dimdoor.bin',     ''),
    466: (None,              '325 bytes; no retail size match'),
    467: ('winlose.bmp',     'Manually identified; pre-release win/lose screen'),
    468: ('wincmbt.icn',     ''),
    469: ('wincmbt.bin',     ''),
    470: ('winlose-wide.bmp', 'Positional match (between wincmbt.icn and losewalk.icn). '
                              'Non-standard BMP: magic=0x21 0x00, width=640, but height field '
                              'bytes 4-5 read 125 (not actual height). True height = '
                              '(size-6)/640 = 504. Decoder must compute height from file size. '
                              'Possibly a pre-release win/lose background, 640x504.'),
    471: (None,              '70 bytes; size matches several view-XX.bin files'),
    472: ('legend.icn',      'Manually identified; size ties losecmbt.icn in retail'),
    473: ('losewalk.icn',    ''),
    474: ('wsnd00.82m',      ''),
    475: ('wsnd01.82m',      'Size ties wsnd02 and wsnd05; positional match'),
    476: ('wsnd02.82m',      'Size ties wsnd01 and wsnd05; positional match'),
    477: ('wsnd03.82m',      ''),
    478: ('wsnd04.82m',      ''),
    479: ('wsnd05.82m',      'Size ties wsnd01 and wsnd02; positional match'),
    480: ('wsnd06.82m',      ''),
    481: ('wsnd10.82m',      ''),
    482: ('wsnd11.82m',      ''),
    483: ('wsnd12.82m',      ''),
    484: ('wsnd13.82m',      ''),
    485: ('wsnd14.82m',      ''),
    486: ('wsnd15.82m',      ''),
    487: ('wsnd16.82m',      ''),
    488: ('wsnd20.82m',      ''),
    489: ('wsnd21.82m',      ''),
    490: ('wsnd22.82m',      ''),
    491: ('wsnd23.82m',      ''),
    492: ('wsnd24.82m',      ''),
    493: ('wsnd25.82m',      ''),
    494: ('wsnd26.82m',      ''),
    495: (None,              '281 bytes; no retail size match — between wsnd and loop blocks'),
    496: ('loop0000.82m',    ''),
    497: ('loop0001.82m',    ''),
    498: ('loop0002.82m',    ''),
    499: ('loop0003.82m',    ''),
    500: ('loop0004.82m',    ''),
    501: ('loop0005.82m',    ''),
    502: ('loop0006.82m',    ''),
    503: ('loop0007.82m',    ''),
    504: ('loop0008.82m',    ''),
    505: ('loop0009.82m',    ''),
    506: ('loop0010.82m',    ''),
    507: ('loop0011.82m',    ''),
    508: ('loop0012.82m',    ''),
    509: ('loop0013.82m',    ''),
    510: ('loop0014.82m',    ''),
    511: ('loop0015.82m',    ''),
    512: ('loop0016.82m',    ''),
    513: ('loop0017.82m',    ''),
    514: ('loop0018.82m',    ''),
    515: ('loop0019.82m',    ''),
    516: ('loop0020.82m',    ''),
    517: ('loop0021.82m',    ''),
    518: ('WINCE00.82M',     ''),
    519: ('WINCE01.82M',     ''),
    520: ('WINCE02.82M',     ''),
    521: ('WINCE03.82M',     ''),
    522: ('WINCE04.82M',     ''),
    523: ('WINCE05.82M',     ''),
    524: ('WINCE06.82M',     ''),
    525: ('WINCE07.82M',     ''),
    526: ('WINCE08.82M',     ''),
    527: ('WINCE09.82M',     ''),
    528: ('WINCE10.82M',     ''),
    529: ('WINCE11.82M',     ''),
    530: ('WINCE12.82M',     ''),
    531: ('WINCE13.82M',     ''),
    532: ('WINCE14.82M',     ''),
    533: ('WINCE15.82M',     ''),
    534: ('WINCE16.82M',     ''),
    535: ('WINCE17.82M',     ''),
    536: ('WINCE18.82M',     ''),
    537: ('WINCE19.82M',     ''),
    538: ('WINCE20.82M',     ''),
    539: ('WINCE21.82M',     ''),
    540: ('WINCE22.82M',     ''),
    541: ('WINCE23.82M',     ''),
    542: ('WINCE24.82M',     ''),
    543: ('WINCE25.82M',     ''),
    544: ('WINCE26.82M',     ''),
    545: ('WINCE27.82M',     ''),
    546: ('ATKSND00.82M',    ''),
    547: ('ATKSND01.82M',    ''),
    548: ('ATKSND02.82M',    ''),
    549: ('ATKSND03.82M',    ''),
    550: ('ATKSND04.82M',    ''),
    551: ('ATKSND05.82M',    ''),
    552: ('ATKSND06.82M',    ''),
    553: ('ATKSND07.82M',    ''),
    554: ('ATKSND08.82M',    ''),
    555: ('ATKSND09.82M',    ''),
    556: ('ATKSND10.82M',    ''),
    557: ('ATKSND11.82M',    ''),
    558: ('ATKSND12.82M',    ''),
    559: ('ATKSND13.82M',    ''),
    560: ('ATKSND14.82M',    ''),
    561: ('ATKSND15.82M',    'Size ties SHOOT15; positional match'),
    562: ('ATKSND16.82M',    ''),
    563: ('ATKSND17.82M',    ''),
    564: ('ATKSND18.82M',    ''),
    565: ('ATKSND19.82M',    ''),
    566: ('ATKSND20.82M',    ''),
    567: ('ATKSND21.82M',    ''),
    568: ('ATKSND22.82M',    ''),
    569: ('ATKSND23.82M',    ''),
    570: ('ATKSND24.82M',    ''),
    571: ('ATKSND25.82M',    ''),
    572: ('ATKSND26.82M',    ''),
    573: ('ATKSND27.82M',    ''),
    574: ('SHOOT01.82M',     ''),
    575: ('SHOOT07.82M',     ''),
    576: ('SHOOT10.82M',     ''),
    577: ('SHOOT14.82M',     ''),
    578: ('SHOOT15.82M',     'Size ties ATKSND15; positional match'),
    579: ('SHOOT18.82M',     ''),
    580: ('MOVE00.82M',      ''),
    581: ('MOVE01.82M',      ''),
    582: ('MOVE02.82M',      ''),
    583: ('MOVE03.82M',      ''),
    584: ('MOVE04.82M',      ''),
    585: ('MOVE05.82M',      ''),
    586: ('MOVE06.82M',      ''),
    587: ('MOVE07.82M',      ''),
    588: ('MOVE08.82M',      ''),
    589: ('MOVE09.82M',      ''),
    590: ('MOVE10.82M',      ''),
    591: ('MOVE12.82M',      'Note: MOVE11 absent from KB'),
    592: ('MOVE13.82M',      ''),
    593: ('MOVE14.82M',      ''),
    594: ('MOVE15.82M',      ''),
    595: ('MOVE16.82M',      ''),
    596: ('MOVE17.82M',      ''),
    597: ('MOVE18.82M',      ''),
    598: ('MOVE19.82M',      ''),
    599: ('MOVE20.82M',      ''),
    600: ('MOVE21.82M',      ''),
    601: ('MOVE22.82M',      ''),
    602: ('MOVE23.82M',      ''),
    603: ('MOVE24.82M',      ''),
    604: ('MOVE25.82M',      ''),
    605: ('MOVE26.82M',      ''),
    606: ('MOVE27.82M',      ''),
    607: ('CATSND00.82M',    ''),
    608: ('CATSND01.82m',    'Manually identified; absent from retail release'),
    609: ('CATSND02.82M',    ''),
    610: (None,              '768-byte PAL; third palette — possibly an alternate or unused palette'),
    611: ('titlebak.bmp',    'Manually identified; pre-release title screen background'),
    612: ('titleext.bmp',    'Manually identified; pre-release title screen extra layer'),
    # Small ICNs at end — no retail size match
    613: ('orngtent.icn',    'Manually identified; pre-release tent colour variant'),
    614: ('redtent.icn',     'Manually identified; pre-release tent colour variant'),
    615: ('greentnt.icn',    'Manually identified; pre-release tent colour variant'),
    616: ('bluetent.icn',    'Manually identified; pre-release tent colour variant'),
    617: ('yelotent.icn',    'Manually identified; pre-release tent colour variant'),
    618: ('purptent.icn',    'Manually identified; pre-release tent colour variant'),
    619: ('whitetnt.icn',    'Manually identified; pre-release tent colour variant'),
    620: ('introcas.icn',    'Manually identified; large pre-release intro castle animation'),
    621: ('introcre.icn',    'Manually identified; large pre-release intro creature animation'),
    622: (None,              '374 bytes; one of a cluster (622-625) at end of archive'),
    623: (None,              '394 bytes; see index 622'),
    624: (None,              '374 bytes; see index 622'),
    625: (None,              '376 bytes; see index 622'),
}


# ===========================================================================
# Folder / file naming
# ===========================================================================

def entry_label(idx, eid, size, name):
    """Return the base name used for this entry's folder or file."""
    name_part = name if name else 'UNKNOWN'
    return f'{idx:04d}_{eid:04X}_{size}_{name_part}'


# ===========================================================================
# Binary helpers
# ===========================================================================

def u16(d, p): return struct.unpack_from('<H', d, p)[0], p + 2
def u32(d, p): return struct.unpack_from('<I', d, p)[0], p + 4
def s16(d, p): return struct.unpack_from('<h', d, p)[0], p + 2


# ===========================================================================
# AGG parser
# ===========================================================================

ENTRY_SIZE  = 10
TABLE_START = 2

def parse_entries(data):
    size = len(data)
    entries = []
    offset = TABLE_START
    index  = 0
    while offset + ENTRY_SIZE <= size:
        entry_id  = struct.unpack_from('<H', data, offset)[0]
        file_off, file_size = struct.unpack_from('<II', data, offset + 2)
        if file_size == 0 or file_off >= size:
            break
        if file_off + file_size > size:
            break
        if entries and file_off < entries[-1]['offset']:
            break
        entries.append({'index': index, 'id': entry_id,
                        'offset': file_off, 'size': file_size})
        offset += ENTRY_SIZE
        index  += 1
    print(f"Detected {len(entries)} entries")
    return entries


# ===========================================================================
# File-type detector
# ===========================================================================

def detect_type(blob):
    n = len(blob)
    if n == 768:
        return 'PAL'
    if n < 6:
        return 'UNKNOWN'
    n_spr = struct.unpack_from('<H', blob, 0)[0]
    total = struct.unpack_from('<I', blob, 2)[0]
    if n_spr > 0 and n_spr <= 4096 and total + 6 == n and 6 + n_spr * 12 <= n:
        return 'ICN'
    n_til = struct.unpack_from('<H', blob, 0)[0]
    tw    = struct.unpack_from('<H', blob, 2)[0]
    th    = struct.unpack_from('<H', blob, 4)[0]
    if n_til > 0 and tw > 0 and th > 0 and 6 + n_til * tw * th == n:
        return 'TIL'
    if blob[0] == 0x21 and blob[1] == 0x00:
        bw = struct.unpack_from('<H', blob, 2)[0]
        bh = struct.unpack_from('<H', blob, 4)[0]
        if bw > 0 and bh > 0 and 6 + bw * bh == n:
            return 'BMP'
    return 'UNKNOWN'


# ===========================================================================
# Palette
# ===========================================================================

def load_palette(pal_data):
    return [
        (min(pal_data[i*3]   * 4, 255),
         min(pal_data[i*3+1] * 4, 255),
         min(pal_data[i*3+2] * 4, 255))
        for i in range(256)
    ]

def save_palette_swatch(palette, path):
    if not PIL_AVAILABLE:
        return
    img = Image.new('RGB', (256, 32))
    px = img.load()
    for i, (r, g, b) in enumerate(palette):
        for y in range(32):
            px[i, y] = (r, g, b)
    img.save(path)


# ===========================================================================
# ICN sprite decoding helpers
# ===========================================================================

def _read_icn_headers(icn_data):
    """
    Parse the ICN/STD/ATK/WLK/WIP header table.
    Returns (n_sprites, headers_list).
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
        t   = (pack >> 24) & 0xFF
        dof =  pack & 0x00FFFFFF
        headers.append({'ox': ox, 'oy': oy, 'w': w, 'h': h,
                        'type': t, 'dof': dof, '_sorted_dofs': None})
    sorted_dofs = sorted(set(h['dof'] for h in headers))
    for h in headers:
        h['_sorted_dofs'] = sorted_dofs
    return n_sprites, headers


def _decode_one_sprite(icn_data, hdr, palette):
    """
    Decode a single sprite from an ICN/STD/ATK/etc. file.
    Returns an RGBA PIL Image, or None if width/height is 0.
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
    mono  = (hdr['type'] == 32)
    x, y  = 0, 0

    while p < p_end:
        cmd = icn_data[p]; p += 1
        if mono:
            if cmd == 0x00:
                x = 0; y += 1
            elif cmd == 0x80:
                break
            elif 0x01 <= cmd <= 0x7F:
                for _ in range(cmd):
                    set_px(x, y, 0, 0, 0, 255); x += 1
            else:
                x += cmd - 0x80
        else:
            if cmd == 0x00:
                x = 0; y += 1
            elif cmd == 0x80:
                break
            elif 0x01 <= cmd <= 0x7F:
                for _ in range(cmd):
                    if p >= p_end: break
                    ci = icn_data[p]; p += 1
                    cr, cg, cb = palette[ci]
                    set_px(x, y, cr, cg, cb, 255); x += 1
            else:
                x += cmd - 0x80

    return Image.frombytes('RGBA', (sw, sh), bytes(buf))


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
# Generic ICN sprite decoder (for ICN / WLK / WIP and plain ICN files)
# ===========================================================================

def decode_icn(icn_data, palette, out_dir):
    if not PIL_AVAILABLE:
        return
    n_sprites, headers = _read_icn_headers(icn_data)
    if n_sprites == 0:
        return
    os.makedirs(out_dir, exist_ok=True)
    for idx, hdr in enumerate(headers):
        img = _decode_one_sprite(icn_data, hdr, palette)
        if img is not None:
            img.save(os.path.join(out_dir, f'{idx:04d}.png'))
    with open(os.path.join(out_dir, 'spec.xml'), 'w') as f:
        f.write(f'<icn count="{n_sprites}">\n')
        for idx, hdr in enumerate(headers):
            f.write(f'  <sprite id="{idx}" file="{idx:04d}.png"'
                    f' offsetX="{hdr["ox"]}" offsetY="{hdr["oy"]}"'
                    f' width="{hdr["w"]}" height="{hdr["h"]}"'
                    f' type="{hdr["type"]}"/>\n')
        f.write('</icn>\n')


# ===========================================================================
# STD decoder  (standing/idle + attack compositing)
# ===========================================================================

# Creatures with tiny F5 (shadow anchor) – overlays are composited directly
# without a large body base underneath.
_SHADOW_ANCHOR_CREATURES = {'wolf', 'gargoyle', 'griffin', 'ghost'}

# Extended creatures have 3 sets of 3 attack overlays instead of one set.
_EXTENDED_CREATURES = {'dragon', 'cyclops', 'phoenix'}

# Hydra has no base frame 5 and no overlay compositing – all frames are
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

    creature = stem.lower()

    # Decode all sprites up-front
    sprites = {}
    for idx, hdr in enumerate(headers):
        sprites[idx] = _decode_one_sprite(icn_data, hdr, palette)

    # Write individual frame PNGs (skip F0 noise, sentinels, and shadow frames)
    SHADOW_THRESHOLD = 20
    SENTINEL_SIZE    = 1

    for idx, img in sprites.items():
        if img is None:
            continue
        hdr = headers[idx]
        if idx == 0:
            continue
        if hdr['w'] <= SENTINEL_SIZE and hdr['h'] <= SENTINEL_SIZE:
            continue
        if idx >= 9 and hdr['h'] <= SHADOW_THRESHOLD:
            continue
        img.save(os.path.join(out_dir, f'{idx:04d}.png'))

    # Build composite attack frames
    if creature in _HYDRA_LIKE:
        _write_std_spec(out_dir, n_sprites, headers, [])
        return

    if creature in _EXTENDED_CREATURES:
        overlay_sets = [
            (6,  7,  8,  'atk0'),
            (9,  10, 11, 'atk1'),
            (12, 13, 14, 'atk2'),
        ]
    else:
        overlay_sets = [
            (6, 7, 8, 'atk'),
        ]

    composites = []

    def make_and_save(body_idx, overlay_idx, name):
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
            composite.save(os.path.join(out_dir, f'{name}.png'))
            composites.append(name)

    base_idx = 5
    for set_entry in overlay_sets:
        up_idx, across_idx, down_idx, set_label = set_entry
        make_and_save(base_idx, up_idx,     f'composite_{set_label}_up')
        make_and_save(base_idx, across_idx, f'composite_{set_label}_across')
        make_and_save(base_idx, down_idx,   f'composite_{set_label}_down')

    _write_std_spec(out_dir, n_sprites, headers, composites)


def _write_std_spec(out_dir, n_sprites, headers, composites):
    with open(os.path.join(out_dir, 'spec.xml'), 'w') as f:
        f.write(f'<icn count="{n_sprites}">\n')
        for idx, hdr in enumerate(headers):
            f.write(
                f'  <sprite id="{idx}" file="{idx:04d}.png"'
                f' offsetX="{hdr["ox"]}" offsetY="{hdr["oy"]}"'
                f' width="{hdr["w"]}" height="{hdr["h"]}"'
                f' type="{hdr["type"]}"/>\n'
            )
        if composites:
            f.write('  <!-- Composite attack frames (base + overlay) -->\n')
            for name in composites:
                f.write(f'  <composite file="{name}.png"/>\n')
        f.write('</icn>\n')


# ===========================================================================
# ATK decoder  (ranged/melee attack + projectile frames)
# ===========================================================================

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

    sprites = {}
    for idx, hdr in enumerate(headers):
        sprites[idx] = _decode_one_sprite(icn_data, hdr, palette)

    # Write individual frame PNGs
    for idx, img in sprites.items():
        if img is None:
            continue
        img.save(os.path.join(out_dir, f'{idx:04d}.png'))

    # Composite attack frames: F0 (base) + F1..F4 (overlays)
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

    # Projectile frames
    proj_frames = []
    for proj_idx in range(5, min(10, n_sprites)):
        img = sprites.get(proj_idx)
        if img is not None:
            name = f'projectile_F{proj_idx}'
            img.save(os.path.join(out_dir, f'{name}.png'))
            proj_frames.append(name)

    # Write spec.xml
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
                f' type="{hdr["type"]}"{role}/>\n'
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
# 82M decoder (raw PCM audio -> WAV)
#
# .82m files are raw PCM with no header.
# Defaults: 11025 Hz, mono, 16-bit signed PCM.
# Optionally prefixed with an "82M " magic header:
#   4 bytes magic + u32 sample_rate + u16 channels + u16 bits_per_sample
# ===========================================================================

_82M_SAMPLE_RATE     = 11025
_82M_CHANNELS        = 1
_82M_BITS_PER_SAMPLE = 16


def decode_82m(raw_data, out_path):
    """Convert raw .82m PCM data to a standard WAV file."""
    offset = 0
    sr  = _82M_SAMPLE_RATE
    ch  = _82M_CHANNELS
    bps = _82M_BITS_PER_SAMPLE

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
# TIL decoder
# ===========================================================================

def decode_til(til_data, palette, out_dir):
    if not PIL_AVAILABLE:
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
        chunk = til_data[pos:pos + tile_sz]; pos += tile_sz
        img = Image.new('RGB', (width, height))
        img.putdata([palette[b] for b in chunk])
        img.save(os.path.join(out_dir, f'{i:04d}.png'))


# ===========================================================================
# BMP decoder
# ===========================================================================

def decode_homm_bmp(bmp_data, palette, out_path):
    if not PIL_AVAILABLE:
        return
    pos = 2
    width,  pos = u16(bmp_data, pos)
    height, pos = u16(bmp_data, pos)
    if width == 0 or height == 0:
        return
    raw = bmp_data[pos:pos + width * height]
    img = Image.new('RGB', (width, height))
    img.putdata([palette[b] for b in raw])
    img.save(out_path)


# ===========================================================================
# Survey helper — writes _survey.txt inside each UNKNOWN folder
# ===========================================================================

def write_survey(blob, idx, eid, size, label, out_dir, also_print=False):
    lines = []
    lines.append(f"UNKNOWN entry survey")
    lines.append(f"  index : {idx}")
    lines.append(f"  id    : {eid:04X}")
    lines.append(f"  size  : {size}")
    lines.append(f"  label : {label}")
    lines.append("")

    # Hex dump — first 128 bytes
    lines.append("Hex dump (first 128 bytes):")
    for row in range(0, min(128, len(blob)), 16):
        chunk = blob[row:row+16]
        hex_s = ' '.join(f'{b:02X}' for b in chunk)
        asc_s = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {row:04X}:  {hex_s:<48}  {asc_s}")
    lines.append("")

    # Structural probes
    if size >= 6:
        ns = struct.unpack_from('<H', blob, 0)[0]
        ts = struct.unpack_from('<I', blob, 2)[0]
        lines.append(f"As ICN : n_sprites={ns}  total_size={ts}  (6+ts={6+ts}, file={size})"
                     + ("  ✓ MATCH" if 6+ts == size and ns > 0 and 6+ns*12 <= size else ""))
        nt = struct.unpack_from('<H', blob, 0)[0]
        tw = struct.unpack_from('<H', blob, 2)[0]
        th = struct.unpack_from('<H', blob, 4)[0]
        if tw > 0 and th > 0:
            lines.append(f"As TIL : n_tiles={nt}  w={tw}  h={th}  (6+n*w*h={6+nt*tw*th}, file={size})"
                         + ("  ✓ MATCH" if 6+nt*tw*th == size else ""))
        bw = struct.unpack_from('<H', blob, 2)[0]
        bh = struct.unpack_from('<H', blob, 4)[0]
        if bw > 0 and bh > 0:
            lines.append(f"As BMP : magic={blob[0]:02X} {blob[1]:02X}  w={bw}  h={bh}  (6+w*h={6+bw*bh}, file={size})"
                         + ("  ✓ MATCH" if blob[0]==0x21 and blob[1]==0x00 and 6+bw*bh==size else ""))

    # ASCII sniff
    ascii_count = sum(1 for b in blob[:min(64, size)] if 32 <= b < 127 or b in (9, 10, 13))
    if ascii_count > min(64, size) * 0.7:
        lines.append("")
        lines.append("Looks like TEXT:")
        lines.append("  " + blob[:64].decode('ascii', errors='replace')
                     .replace('\n', '\\n').replace('\r', '\\r'))

    lines.append("")
    lines.append("observations: ")   # blank line for manual annotation

    text = '\n'.join(lines)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, '_survey.txt').write_text(text)
    if also_print:
        print(text)


# ===========================================================================
# Index TSV writer
# ===========================================================================

def write_index_tsv(entries_meta, out_path):
    with open(out_path, 'w', newline='') as f:
        f.write('index\tkb_id\tsize\tdetected_type\tknown_name\tobservations\n')
        for m in entries_meta:
            name = m['name'] or ''
            obs  = m['obs'].replace('\t', ' ')
            f.write(f"{m['index']}\t{m['id']:04X}\t{m['size']}\t{m['ftype']}\t{name}\t{obs}\n")


# ===========================================================================
# Main extraction
# ===========================================================================

def extract(agg_path, palette_index=8, survey_stdout=False):
    agg_path = Path(agg_path)
    if not agg_path.exists():
        print(f"ERROR: file not found: {agg_path}")
        sys.exit(1)

    data = agg_path.read_bytes()
    out_root = Path(agg_path.stem)
    out_root.mkdir(exist_ok=True)

    print(f"Reading {agg_path} ({len(data):,} bytes) ...")
    entries = parse_entries(data)
    print()

    # --- Load all PAL entries first ---
    palettes = {}
    for e in entries:
        blob = data[e['offset']:e['offset'] + e['size']]
        if len(blob) == 768:
            idx = e['index']
            palettes[idx] = load_palette(blob)
            name, _ = NAME_TABLE.get(idx, (None, ''))
            label = entry_label(idx, e['id'], e['size'], name)
            swatch = out_root / f'{label}_swatch.png'
            save_palette_swatch(palettes[idx], swatch)
            print(f"  PAL  {label}  ->  {swatch.name}")

    if not palettes:
        print("WARNING: No PAL entries found - using greyscale fallback.")
        palettes[palette_index] = [(i, i, i) for i in range(256)]

    palette = palettes.get(palette_index)
    if palette is None:
        fallback_idx = next(iter(palettes))
        palette = palettes[fallback_idx]
        print(f"WARNING: Palette index {palette_index} not found; using index {fallback_idx}.")

    print(f"\nUsing palette index {palette_index} for decoding.\n")

    counts = {'ICN': 0, 'STD': 0, 'ATK': 0, 'WLK': 0, 'WIP': 0,
              'TIL': 0, 'BMP': 0, 'PAL': 0, '82M': 0, 'UNKNOWN': 0}
    entries_meta = []

    for e in entries:
        blob  = data[e['offset']:e['offset'] + e['size']]
        idx   = e['index']
        eid   = e['id']
        size  = e['size']

        name, obs = NAME_TABLE.get(idx, (None, ''))
        label = entry_label(idx, eid, size, name)

        # Determine file extension from known name, then fall back to content detection
        name_ext = Path(name).suffix.upper() if name and '.' in name else ''

        # Route by known extension first, then by detected type
        if name_ext == '.82M':
            ftype = '82M'
        elif name_ext == '.STD':
            ftype = 'STD'
        elif name_ext == '.ATK':
            ftype = 'ATK'
        elif name_ext == '.WLK':
            ftype = 'WLK'
        elif name_ext == '.WIP':
            ftype = 'WIP'
        else:
            ftype = detect_type(blob)

        counts[ftype] = counts.get(ftype, 0) + 1
        entries_meta.append({'index': idx, 'id': eid, 'size': size,
                             'ftype': ftype, 'name': name, 'obs': obs,
                             'label': label})

        if ftype == 'PAL':
            raw_path = out_root / f'{label}.bin'
            raw_path.write_bytes(blob)

        elif ftype == 'ICN':
            icn_dir = out_root / label
            n_spr   = struct.unpack_from('<H', blob, 0)[0]
            print(f"  ICN  {label}/  ({n_spr} sprites)")
            try:
                decode_icn(blob, palette, str(icn_dir))
            except Exception as ex:
                print(f"    ERROR: {ex}")

        elif ftype == 'STD':
            sprite_dir = out_root / label
            stem_name  = Path(name).stem if name else label
            try:
                n_spr = struct.unpack_from('<H', blob, 0)[0]
            except Exception:
                n_spr = 0
            print(f"  STD  {label}/  ({n_spr} sprites)")
            try:
                decode_std(blob, palette, str(sprite_dir), stem_name)
            except Exception as ex:
                import traceback
                print(f"    ERROR: {ex}")
                traceback.print_exc()

        elif ftype == 'ATK':
            sprite_dir = out_root / label
            stem_name  = Path(name).stem if name else label
            try:
                n_spr = struct.unpack_from('<H', blob, 0)[0]
            except Exception:
                n_spr = 0
            print(f"  ATK  {label}/  ({n_spr} sprites)")
            try:
                decode_atk(blob, palette, str(sprite_dir), stem_name)
            except Exception as ex:
                import traceback
                print(f"    ERROR: {ex}")
                traceback.print_exc()

        elif ftype == 'WLK':
            sprite_dir = out_root / label
            try:
                n_spr = struct.unpack_from('<H', blob, 0)[0]
            except Exception:
                n_spr = 0
            print(f"  WLK  {label}/  ({n_spr} sprites)")
            try:
                decode_icn(blob, palette, str(sprite_dir))
            except Exception as ex:
                import traceback
                print(f"    ERROR: {ex}")
                traceback.print_exc()

        elif ftype == 'WIP':
            sprite_dir = out_root / label
            try:
                n_spr = struct.unpack_from('<H', blob, 0)[0]
            except Exception:
                n_spr = 0
            print(f"  WIP  {label}/  ({n_spr} sprites)")
            try:
                decode_icn(blob, palette, str(sprite_dir))
            except Exception as ex:
                import traceback
                print(f"    ERROR: {ex}")
                traceback.print_exc()

        elif ftype == 'TIL':
            til_dir = out_root / label
            n_til   = struct.unpack_from('<H', blob, 0)[0]
            tw      = struct.unpack_from('<H', blob, 2)[0]
            th      = struct.unpack_from('<H', blob, 4)[0]
            print(f"  TIL  {label}/  ({n_til} tiles, {tw}x{th})")
            try:
                decode_til(blob, palette, str(til_dir))
            except Exception as ex:
                print(f"    ERROR: {ex}")

        elif ftype == 'BMP':
            bw  = struct.unpack_from('<H', blob, 2)[0]
            bh  = struct.unpack_from('<H', blob, 4)[0]
            png = out_root / f'{label}.png'
            print(f"  BMP  {label}.png  ({bw}x{bh})")
            try:
                decode_homm_bmp(blob, palette, str(png))
            except Exception as ex:
                print(f"    ERROR: {ex}")

        elif ftype == '82M':
            wav_path = out_root / f'{label}.wav'
            print(f"  SND  {label}.wav")
            try:
                decode_82m(blob, str(wav_path))
            except Exception as ex:
                print(f"    ERROR: {ex}  (saving raw instead)")
                raw_path = out_root / f'{label}.bin'
                raw_path.write_bytes(blob)

        else:  # UNKNOWN
            unk_dir = out_root / label
            unk_dir.mkdir(exist_ok=True)
            (unk_dir / '_raw.bin').write_bytes(blob)
            write_survey(blob, idx, eid, size, label, str(unk_dir),
                         also_print=survey_stdout)
            print(f"  UNK  {label}/  ({obs[:60] + '...' if len(obs) > 60 else obs})")

    # Write master index TSV
    tsv_path = out_root / '_index.tsv'
    write_index_tsv(entries_meta, tsv_path)
    print(f"\nIndex written to {tsv_path}")

    print()
    print("=== Summary ===")
    for ftype, cnt in sorted(counts.items()):
        print(f"  {ftype:<8} {cnt}")
    print(f"  {'TOTAL':<8} {sum(counts.values())}")
    print(f"\nDone. All files extracted to '{out_root}/'")


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Extract KB.AGG with named output folders for verification.')
    parser.add_argument('agg_file', help='Path to kb.agg')
    parser.add_argument('--palette', type=int, default=8, metavar='INDEX',
                        help='Palette entry index to use for decoding (default: 8)')
    parser.add_argument('--survey', action='store_true',
                        help='Also print survey info to stdout for UNKNOWN files')
    args = parser.parse_args()
    extract(args.agg_file, palette_index=args.palette, survey_stdout=args.survey)
