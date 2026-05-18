#pragma once
#include "image.h"
#include "palette.h"
#include <vector>

namespace homm1 {

// Decode a .bkg battle background sky strip.
//
// Layout (identical to the custom HoMM BMP format):
//   u16 magic  (0x0021 — bytes 0x21 0x00)
//   u16 width
//   u16 height
//   width*height palette index bytes (row-major, RGB via palette)
//
// Returns a decoded RGB Image.
Image decode_bkg(const std::vector<uint8_t>& raw, const Palette& pal);

} // namespace homm1
