#pragma once
#include "palette.h"
#include <string>
#include <vector>

namespace homm1 {

// Decode a .atk ranged-attack animation file and write output to out_dir.
//
// Frame layout:
//   F0      base pose (always visible)
//   F1–F4   attack overlays — each composited on top of F0
//   F5–F9   projectile sprites (arrow, bolt, fireball, etc.)
//
// Output files:
//   0000.png … (all individual frames)
//   composite_atk_F1.png … composite_atk_F4.png
//   projectile_F5.png … projectile_F9.png  (whichever are present)
//   spec.xml
void decode_and_save_atk(const std::vector<uint8_t>& raw,
                         const Palette& pal,
                         const std::string& out_dir);

} // namespace homm1
