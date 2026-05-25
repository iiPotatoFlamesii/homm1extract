#include "atk.h"
#include "icn.h"
#include "image.h"
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace homm1 {

namespace fs = std::filesystem;

void decode_and_save_atk(const std::vector<uint8_t>& raw,
                         const Palette& pal,
                         const std::string& out_dir,
                         const std::string& stem) {
    const IcnFile icn = decode_icn(raw, pal, stem);
    const int n = static_cast<int>(icn.frames.size());
    if (n == 0) return;

    fs::create_directories(out_dir);

    // Write all individual frame PNGs.
    for (int i = 0; i < n; ++i) {
        if (icn.frames[i].empty()) continue;
        char fname[32]; std::snprintf(fname, sizeof(fname), "%04d.png", i);
        save_png(icn.frames[i], out_dir + "/" + fname);
    }

    // -----------------------------------------------------------------------
    // Composite frames: F0 (base) + F1..F4 (overlays)
    // -----------------------------------------------------------------------
    std::vector<std::string> composites;

    const Image& base_img = icn.frames[0];
    const SpriteHeader& bh = icn.headers[0];

    if (!base_img.empty()) {
        for (int oi = 1; oi <= 4 && oi < n; ++oi) {
            const Image& over_img = icn.frames[oi];
            if (over_img.empty()) continue;

            const SpriteHeader& oh = icn.headers[oi];
            const Image composite = composite_images({
                { &base_img, bh.offset_x, bh.offset_y },
                { &over_img, oh.offset_x, oh.offset_y },
            });
            if (composite.empty()) continue;

            char name[64]; std::snprintf(name, sizeof(name), "composite_atk_F%d", oi);
            const std::string fname = std::string(name) + ".png";
            save_png(composite, out_dir + "/" + fname);
            composites.push_back(fname);
        }
    }

    // -----------------------------------------------------------------------
    // Projectile frames: F5..F9 — exported individually with clear names
    // -----------------------------------------------------------------------
    std::vector<std::string> projectiles;
    for (int pi = 5; pi <= 9 && pi < n; ++pi) {
        if (icn.frames[pi].empty()) continue;
        char name[64]; std::snprintf(name, sizeof(name), "projectile_F%d.png", pi);
        save_png(icn.frames[pi], out_dir + "/" + name);
        projectiles.push_back(name);
    }

    // -----------------------------------------------------------------------
    // spec.xml
    // -----------------------------------------------------------------------
    std::ofstream xml(out_dir + "/spec.xml");
    if (!xml) return;

    xml << "<icn count=\"" << n << "\">\n";
    for (int i = 0; i < n; ++i) {
        const auto& h = icn.headers[i];
        char fname[32]; std::snprintf(fname, sizeof(fname), "%04d.png", i);
        const char* role = (i == 0)      ? " role=\"base\""
                         : (i <= 4)      ? " role=\"overlay\""
                         : (i <= 9)      ? " role=\"projectile\""
                         : "";
        xml << "  <sprite id=\"" << i << "\""
            << " file=\"" << fname << "\""
            << " offsetX=\"" << h.offset_x << "\""
            << " offsetY=\"" << h.offset_y << "\""
            << " width=\""   << h.width    << "\""
            << " height=\""  << h.height   << "\""
            << role << "/>\n";
    }
    if (!composites.empty()) {
        xml << "  <!-- Composite attack frames (base F0 + overlay Fn) -->\n";
        for (const auto& c : composites)
            xml << "  <composite file=\"" << c << "\"/>\n";
    }
    if (!projectiles.empty()) {
        xml << "  <!-- Projectile frames -->\n";
        for (const auto& p : projectiles)
            xml << "  <composite file=\"" << p << "\" role=\"projectile\"/>\n";
    }
    xml << "</icn>\n";
}

} // namespace homm1
