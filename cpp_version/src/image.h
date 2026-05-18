#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace homm1 {

struct Color { uint8_t r, g, b; };

struct Image {
    int width = 0, height = 0;
    std::vector<uint8_t> pixels; // RGBA, row-major

    Image() = default;
    Image(int w, int h);

    void set_pixel(int x, int y, uint8_t r, uint8_t g, uint8_t b, uint8_t a);
    void set_pixel_rgb(int x, int y, const Color& c);

    bool empty() const { return width == 0 || height == 0; }
};

// Alpha-composite src onto dst at pixel position (dx, dy).
// src pixels with alpha=0 are skipped; opaque src pixels overwrite dst.
void alpha_composite(Image& dst, const Image& src, int dx, int dy);

// Composite a list of (image, offsetX, offsetY) onto a shared canvas whose
// bounds are derived from the sprite header offsets, exactly as the Python
// version does:
//
//   canvas_left  = min(offsetX)
//   canvas_top   = min(offsetY)
//   canvas_right = max(offsetX + width)
//   canvas_bot   = max(offsetY + height)
//   paste sprite i at (offsetX_i - canvas_left, offsetY_i - canvas_top)
//
// Returns the composited RGBA image.
struct SpriteLayer {
    const Image* img;
    int offset_x;
    int offset_y;
};
Image composite_images(const std::vector<SpriteLayer>& layers);

void save_png(const Image& img, const std::string& path);

} // namespace homm1
