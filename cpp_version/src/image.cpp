#include "image.h"
#include <algorithm>
#include <climits>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <zlib.h>

namespace homm1 {

// ---------------------------------------------------------------------------
// Image
// ---------------------------------------------------------------------------

Image::Image(int w, int h)
    : width(w), height(h), pixels(w * h * 4, 0) {}

void Image::set_pixel(int x, int y, uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const int base = (y * width + x) * 4;
    pixels[base + 0] = r;
    pixels[base + 1] = g;
    pixels[base + 2] = b;
    pixels[base + 3] = a;
}

void Image::set_pixel_rgb(int x, int y, const Color& c) {
    set_pixel(x, y, c.r, c.g, c.b, 255);
}

// ---------------------------------------------------------------------------
// Compositing
// ---------------------------------------------------------------------------

void alpha_composite(Image& dst, const Image& src, int dx, int dy) {
    for (int sy = 0; sy < src.height; ++sy) {
        const int dy2 = dy + sy;
        if (dy2 < 0 || dy2 >= dst.height) continue;
        for (int sx = 0; sx < src.width; ++sx) {
            const int dx2 = dx + sx;
            if (dx2 < 0 || dx2 >= dst.width) continue;
            const int src_base = (sy * src.width + sx) * 4;
            const uint8_t a = src.pixels[src_base + 3];
            if (a == 0) continue; // fully transparent — skip
            const int dst_base = (dy2 * dst.width + dx2) * 4;
            dst.pixels[dst_base + 0] = src.pixels[src_base + 0];
            dst.pixels[dst_base + 1] = src.pixels[src_base + 1];
            dst.pixels[dst_base + 2] = src.pixels[src_base + 2];
            dst.pixels[dst_base + 3] = a;
        }
    }
}

Image composite_images(const std::vector<SpriteLayer>& layers) {
    if (layers.empty()) return {};

    int min_x = INT_MAX, min_y = INT_MAX;
    int max_x = INT_MIN, max_y = INT_MIN;

    for (const auto& l : layers) {
        if (!l.img || l.img->empty()) continue;
        min_x = std::min(min_x, l.offset_x);
        min_y = std::min(min_y, l.offset_y);
        max_x = std::max(max_x, l.offset_x + l.img->width);
        max_y = std::max(max_y, l.offset_y + l.img->height);
    }

    if (min_x == INT_MAX || max_x <= min_x || max_y <= min_y) return {};

    Image canvas(max_x - min_x, max_y - min_y);
    for (const auto& l : layers) {
        if (!l.img || l.img->empty()) continue;
        alpha_composite(canvas, *l.img, l.offset_x - min_x, l.offset_y - min_y);
    }
    return canvas;
}

// ---------------------------------------------------------------------------
// Minimal PNG encoder
//
// PNG structure:
//   8-byte signature
//   IHDR chunk  (13 bytes)
//   IDAT chunk  (zlib-compressed filter+scanline data)
//   IEND chunk
//
// Each scanline is prefixed with a 0x00 (None) filter byte.
// ---------------------------------------------------------------------------

static void write_u32_be(std::vector<uint8_t>& buf, uint32_t v) {
    buf.push_back((v >> 24) & 0xFF);
    buf.push_back((v >> 16) & 0xFF);
    buf.push_back((v >>  8) & 0xFF);
    buf.push_back((v      ) & 0xFF);
}

static uint32_t crc32_of(const uint8_t* data, size_t len) {
    return static_cast<uint32_t>(::crc32(0, data, static_cast<uInt>(len)));
}

static void write_chunk(std::vector<uint8_t>& out,
                        const char type[4],
                        const std::vector<uint8_t>& data) {
    write_u32_be(out, static_cast<uint32_t>(data.size()));
    const size_t crc_start = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    const uint32_t crc = crc32_of(out.data() + crc_start, 4 + data.size());
    write_u32_be(out, crc);
}

void save_png(const Image& img, const std::string& path) {
    if (img.width <= 0 || img.height <= 0)
        throw std::runtime_error("save_png: zero-size image");

    // Build raw scanline data: filter_byte(0) + 4 bytes per pixel
    const size_t row_bytes = 1 + static_cast<size_t>(img.width) * 4;
    std::vector<uint8_t> raw(row_bytes * img.height);
    for (int y = 0; y < img.height; ++y) {
        raw[y * row_bytes] = 0x00; // None filter
        std::memcpy(raw.data() + y * row_bytes + 1,
                    img.pixels.data() + y * img.width * 4,
                    img.width * 4);
    }

    // zlib-compress the raw data
    uLong bound = compressBound(static_cast<uLong>(raw.size()));
    std::vector<uint8_t> compressed(bound);
    if (compress2(compressed.data(), &bound,
                  raw.data(), static_cast<uLong>(raw.size()),
                  Z_BEST_COMPRESSION) != Z_OK)
        throw std::runtime_error("save_png: zlib compression failed");
    compressed.resize(bound);

    // Assemble PNG bytes
    std::vector<uint8_t> out;
    out.reserve(64 + compressed.size());

    // PNG signature
    const uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    out.insert(out.end(), sig, sig + 8);

    // IHDR: width, height, bit_depth=8, color_type=6 (RGBA)
    {
        std::vector<uint8_t> ihdr(13);
        ihdr[0] = (img.width  >> 24) & 0xFF;
        ihdr[1] = (img.width  >> 16) & 0xFF;
        ihdr[2] = (img.width  >>  8) & 0xFF;
        ihdr[3] = (img.width       ) & 0xFF;
        ihdr[4] = (img.height >> 24) & 0xFF;
        ihdr[5] = (img.height >> 16) & 0xFF;
        ihdr[6] = (img.height >>  8) & 0xFF;
        ihdr[7] = (img.height      ) & 0xFF;
        ihdr[8]  = 8;   // bit depth
        ihdr[9]  = 6;   // color type: RGBA
        ihdr[10] = 0;   // compression
        ihdr[11] = 0;   // filter method
        ihdr[12] = 0;   // interlace: none
        write_chunk(out, "IHDR", ihdr);
    }

    // IDAT
    write_chunk(out, "IDAT", compressed);

    // IEND
    write_chunk(out, "IEND", {});

    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("save_png: cannot open for writing: " + path);
    if (!f.write(reinterpret_cast<const char*>(out.data()), out.size()))
        throw std::runtime_error("save_png: write failed: " + path);
}

} // namespace homm1
