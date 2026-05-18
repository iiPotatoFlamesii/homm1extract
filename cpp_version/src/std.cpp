#include "std.h"
#include "icn.h"
#include "image.h"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace homm1 {

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Creature classification
// ---------------------------------------------------------------------------

// Extended creatures have 33 frames with 3 sets of attack overlays.
static bool is_extended(const std::string& stem) {
    static const std::set<std::string> s = {"dragon","phoenix","cyclops"};
    std::string lower = stem;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    return s.count(lower) > 0;
}

// Hydra has 16 frames, all independent — no base/overlay compositing.
static bool is_hydra_like(const std::string& stem) {
    std::string lower = stem;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
    return lower == "hydra";
}

// ---------------------------------------------------------------------------
// Frame layout constants
//
// Standard 18-frame layout:
//   F0  noise (skip)
//   F1  standing       F10 shadow
//   F2  death          F11 shadow
//   F3  attack 1       F12 shadow
//   F4  attack 2       F13 shadow
//   F5  base pose
//   F6  atk-up         F15 shadow
//   F7  atk-across     F16 shadow
//   F8  atk-down       F17 shadow
//   F9  sentinel (1x1)
//   F14 sentinel (1x1)
//
// Extended 33-frame layout:
//   F0–F5   same as standard
//   F6–F8   overlay set 0  (up/across/down)
//   F9–F11  overlay set 1
//   F12–F14 overlay set 2
//   F15     sentinel
//   F16–F19 shadows for F1–F4
//   F20     sentinel
//   F21–F29 shadows for overlay sets 0–2
//   F30–F32 extra shadow copies (identical to F27–F29)
//
// Hydra 16-frame layout:
//   F0       noise
//   F1–F7    independent full-body frames
//   F8       sentinel
//   F9–F15   shadows for F1–F7
// ---------------------------------------------------------------------------

static constexpr int SHADOW_HEIGHT_MAX = 20; // frames with h <= this are shadows
static constexpr int SENTINEL_SIZE     = 1;  // 1x1 sentinel frames

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Write a single frame PNG; returns true on success.
static bool write_frame(const Image& img, const std::string& path) {
    if (img.empty()) return false;
    try {
        save_png(img, path);
        return true;
    } catch (...) { return false; }
}

// Make and save a composite of base + overlay using their header offsets.
// Returns the output filename stem (without directory) on success, or "".
static std::string make_composite(const IcnFile& icn,
                                  int base_idx,
                                  int overlay_idx,
                                  const std::string& out_dir,
                                  const std::string& name) {
    if (base_idx    >= static_cast<int>(icn.frames.size())) return {};
    if (overlay_idx >= static_cast<int>(icn.frames.size())) return {};

    const Image& base_img = icn.frames[base_idx];
    const Image& over_img = icn.frames[overlay_idx];
    if (base_img.empty() || over_img.empty()) return {};

    const SpriteHeader& bh = icn.headers[base_idx];
    const SpriteHeader& oh = icn.headers[overlay_idx];

    const Image composite = composite_images({
        { &base_img, bh.offset_x, bh.offset_y },
        { &over_img, oh.offset_x, oh.offset_y },
    });
    if (composite.empty()) return {};

    const std::string fname = name + ".png";
    save_png(composite, out_dir + "/" + fname);
    return fname;
}

// Write spec.xml.
static void write_spec(const IcnFile& icn,
                       const std::vector<std::string>& composites,
                       const std::string& out_dir) {
    std::ofstream xml(out_dir + "/spec.xml");
    if (!xml) return;

    const int n = static_cast<int>(icn.headers.size());
    xml << "<icn count=\"" << n << "\">\n";
    for (int i = 0; i < n; ++i) {
        const auto& h = icn.headers[i];
        char fname[32]; std::snprintf(fname, sizeof(fname), "%04d.png", i);
        xml << "  <sprite id=\"" << i << "\""
            << " file=\"" << fname << "\""
            << " offsetX=\"" << h.offset_x << "\""
            << " offsetY=\"" << h.offset_y << "\""
            << " width=\""   << h.width    << "\""
            << " height=\""  << h.height   << "\""
            << " type=\""    << static_cast<int>(h.type) << "\"/>\n";
    }
    if (!composites.empty()) {
        xml << "  <!-- Composite attack frames (base + overlay) -->\n";
        for (const auto& c : composites)
            xml << "  <composite file=\"" << c << "\"/>\n";
    }
    xml << "</icn>\n";
}

// ---------------------------------------------------------------------------
// decode_and_save_std
// ---------------------------------------------------------------------------

void decode_and_save_std(const std::vector<uint8_t>& raw,
                         const Palette& pal,
                         const std::string& out_dir,
                         const std::string& stem) {
    const IcnFile icn = decode_icn(raw, pal);
    const int n = static_cast<int>(icn.frames.size());
    if (n == 0) return;

    fs::create_directories(out_dir);

    // -----------------------------------------------------------------------
    // Write individual body-frame PNGs.
    // Skip: F0 (noise), 1x1 sentinels, shadow strips (h <= 20 at idx >= 9).
    // -----------------------------------------------------------------------
    for (int i = 0; i < n; ++i) {
        if (i == 0) continue;
        const auto& h = icn.headers[i];
        if (h.width <= SENTINEL_SIZE && h.height <= SENTINEL_SIZE) continue;
        if (i >= 9 && h.height <= SHADOW_HEIGHT_MAX) continue;
        if (icn.frames[i].empty()) continue;

        char fname[32]; std::snprintf(fname, sizeof(fname), "%04d.png", i);
        write_frame(icn.frames[i], out_dir + "/" + fname);
    }

    // -----------------------------------------------------------------------
    // Composite attack frames
    // -----------------------------------------------------------------------
    std::vector<std::string> composites;

    if (is_hydra_like(stem)) {
        // No compositing — all frames are independent full-body poses.
        write_spec(icn, composites, out_dir);
        return;
    }

    // Helper lambda to attempt a composite and record its name.
    auto try_composite = [&](int base_idx, int over_idx, const std::string& name) {
        const auto fname = make_composite(icn, base_idx, over_idx, out_dir, name);
        if (!fname.empty()) composites.push_back(fname);
    };

    constexpr int BASE = 5;

    if (is_extended(stem)) {
        // Three overlay sets: F6-8, F9-11, F12-14
        const char* dirs[3] = {"up", "across", "down"};
        for (int set = 0; set < 3; ++set) {
            const int first_overlay = 6 + set * 3;
            for (int d = 0; d < 3; ++d) {
                char name[64];
                std::snprintf(name, sizeof(name), "composite_atk%d_%s", set, dirs[d]);
                try_composite(BASE, first_overlay + d, name);
            }
        }
    } else {
        // Standard: single overlay set F6, F7, F8
        try_composite(BASE, 6, "composite_atk_up");
        try_composite(BASE, 7, "composite_atk_across");
        try_composite(BASE, 8, "composite_atk_down");
    }

    write_spec(icn, composites, out_dir);
}

} // namespace homm1
