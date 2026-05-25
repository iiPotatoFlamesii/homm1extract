#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include "image.h"
#include "palette.h"

namespace homm1 {

struct SpriteHeader {
    int16_t  offset_x;   // hotspot X (for game engine, not canvas offset)
    int16_t  offset_y;   // hotspot Y
    uint16_t width;
    uint16_t height;
    uint32_t data_off;   // byte offset from file[6] to this sprite's pixel data
};

struct IcnFile {
    std::vector<SpriteHeader> headers;
    std::vector<Image>        frames;  // decoded RGBA images, same order as headers
};

// Decode an ICN file blob.  Sprites with zero dimensions are skipped.
// Truncated pixel data is decoded as far as possible (remaining = transparent).
// Throws std::runtime_error on a malformed header.
IcnFile decode_icn(const std::vector<uint8_t>& data, const Palette& pal, const std::string& icn_name);

// Write all frames to out_dir as 0000.png, 0001.png, … plus spec.xml.
void save_icn(const IcnFile& icn, const std::string& out_dir);

} // namespace homm1
