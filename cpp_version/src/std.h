#pragma once
#include "icn.h"
#include "image.h"
#include "palette.h"
#include <string>
#include <vector>

namespace homm1 {

// Decode a .std creature animation file and write output to out_dir.
//
// Individual frame PNGs (0001.png … 0008.png) are written for all
// non-noise, non-sentinel, non-shadow body frames.
//
// Composite attack PNGs are also written:
//   Standard creatures (18 frames):
//     composite_atk_up.png, composite_atk_across.png, composite_atk_down.png
//
//   Extended creatures – dragon, phoenix, cyclops (33 frames):
//     composite_atk0_up.png … composite_atk2_down.png  (9 total)
//
//   Hydra (16 frames, no base/overlay): individual frames only.
//
//   Flying creatures – wolf, gargoyle, griffin, ghost: F5 is a tiny
//   shadow-anchor patch rather than a full body; compositing still works
//   because all sprites share the same offsetX/Y anchor coordinate system.
//
// A spec.xml listing all sprite headers plus composite filenames is written.
void decode_and_save_std(const std::vector<uint8_t>& raw,
                         const Palette& pal,
                         const std::string& out_dir,
                         const std::string& stem);

} // namespace homm1
