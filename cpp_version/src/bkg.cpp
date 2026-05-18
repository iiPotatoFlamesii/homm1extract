#include "bkg.h"
#include <cstring>
#include <stdexcept>

namespace homm1 {

static uint16_t r_u16(const uint8_t* d, size_t& p) {
    uint16_t v; std::memcpy(&v, d + p, 2); p += 2; return v;
}

Image decode_bkg(const std::vector<uint8_t>& raw, const Palette& pal) {
    if (raw.size() < 6)
        throw std::runtime_error("BKG file too small");

    const uint8_t* d = raw.data();
    size_t pos = 0;

    // Magic: 0x21 0x00 (same as the custom HoMM BMP format)
    const uint8_t magic_lo = d[pos++];
    const uint8_t magic_hi = d[pos++];
    if (magic_lo != 0x21 || magic_hi != 0x00) {
        // Not fatal — some BKG files omit or vary the magic.
        // Rewind and try to decode anyway; dimensions are likely valid.
        pos = 0;
        pos += 2; // skip whatever was there
    }

    const uint16_t width  = r_u16(d, pos);
    const uint16_t height = r_u16(d, pos);

    if (width == 0 || height == 0)
        throw std::runtime_error("BKG has zero dimensions");

    const size_t n_pixels = static_cast<size_t>(width) * height;
    if (pos + n_pixels > raw.size())
        throw std::runtime_error("BKG pixel data truncated");

    Image img(width, height);
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x)
            img.set_pixel_rgb(x, y, pal[d[pos++]]);

    return img;
}

} // namespace homm1
