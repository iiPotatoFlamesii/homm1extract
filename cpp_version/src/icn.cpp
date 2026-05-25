#include "icn.h"
#include <map>
#include <cctype>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <set>

namespace homm1 {

namespace fs = std::filesystem;

// ---------------------------------------------------------------------------
// Little-endian helpers
// ---------------------------------------------------------------------------
static uint16_t r_u16(const uint8_t* d, size_t& p) {
    uint16_t v; std::memcpy(&v, d + p, 2); p += 2; return v;
}
static int16_t r_s16(const uint8_t* d, size_t& p) {
    int16_t v; std::memcpy(&v, d + p, 2); p += 2; return v;
}
static uint32_t r_u32(const uint8_t* d, size_t& p) {
    uint32_t v; std::memcpy(&v, d + p, 4); p += 4; return v;
}

const std::vector<std::string> GLOBAL_MONO_SPRITES = {"losewalk", "font", "smalfont", "radar", "shadow32"};
const std::map<std::string, std::vector<uint8_t>> SUB_MONO_SPRITES = {
    {"swapbtn", {2}},
    {"locators", {20}},
    {"catapult", {15, 16}}
};

std::string uppercase_string(const std::string& in) {
    std::string result = "";
    for(int i = 0; i < in.size(); i++) {
        result += std::toupper((unsigned char)in[i]);
    }

    return result;
};

// ---------------------------------------------------------------------------
// decode_icn
// ---------------------------------------------------------------------------

IcnFile decode_icn(const std::vector<uint8_t>& raw, const Palette& pal, const std::string& icn_name) {
    IcnFile result;
    if (raw.size() < 6)
        throw std::runtime_error("ICN file too small");

    const uint8_t* d = raw.data();
    size_t pos = 0;

    const uint16_t n_sprites = r_u16(d, pos);
    /* total_data_size = */ r_u32(d, pos); // unused — we use raw.size()

    if (n_sprites == 0) return result;

    // Read sprite headers (12 bytes each).
    result.headers.reserve(n_sprites);
    for (uint16_t i = 0; i < n_sprites; ++i) {
        SpriteHeader h;
        h.offset_x = r_s16(d, pos);
        h.offset_y = r_s16(d, pos);
        h.width    = r_u16(d, pos);
        h.height   = r_u16(d, pos);
        const uint32_t packed = r_u32(d, pos);
        h.data_off = packed;
        result.headers.push_back(h);
    }

    // Build a sorted set of all data_off values so we can find each sprite's
    // end boundary — sprite data may not be laid out in header order on disk.
    std::set<uint32_t> dof_set;
    for (const auto& h : result.headers) dof_set.insert(h.data_off);
    std::vector<uint32_t> sorted_dofs(dof_set.begin(), dof_set.end());

    auto data_end_for = [&](uint32_t dof) -> size_t {
        for (uint32_t d2 : sorted_dofs)
            if (d2 > dof) return 6 + d2;
        return raw.size();
    };

    result.frames.reserve(n_sprites);

    bool is_global_mono = std::count(GLOBAL_MONO_SPRITES.begin(),
                                     GLOBAL_MONO_SPRITES.end(), icn_name) > 0;

    for (uint16_t idx = 0; idx < n_sprites; ++idx) {
        const SpriteHeader& hdr = result.headers[idx];
        if (hdr.width == 0 || hdr.height == 0) {
            result.frames.emplace_back(); // empty placeholder
            continue;
        }

        Image img(hdr.width, hdr.height); // all pixels start transparent

        bool is_sub_mono = false;

        if(SUB_MONO_SPRITES.count(icn_name) > 0) {
            std::vector<uint8_t> mono_idxs = SUB_MONO_SPRITES.at(icn_name);
            if(std::count(mono_idxs.begin(), mono_idxs.end(), idx) > 0) {
                is_sub_mono = true;
            }
        }

        size_t extPos = icn_name.find_last_of('.');
        if(idx > 5 && extPos != std::string::npos) {
            std::string fileExt = uppercase_string(icn_name.substr(extPos));
            if(fileExt == ".WLK") {
                is_sub_mono = true;
            }
        }

        size_t p       = 6 + hdr.data_off;
        size_t p_end   = data_end_for(hdr.data_off);
        const bool mono = is_global_mono || is_sub_mono;
        int x = 0, y = 0;

        while (p < p_end) {
            const uint8_t cmd = d[p++];

            if (cmd == 0x00) {
                x = 0; ++y;
            } else if (cmd == 0x80) {
                break;
            } else if (cmd >= 0x01 && cmd <= 0x7F) {
                if(mono) {
                    for (int n = 0; n < cmd; ++n)
                        img.set_pixel(x++, y, 0, 0, 0, 255);
                } else {
                    // Literal run: next cmd bytes are palette indices
                    for (int n = 0; n < cmd && p < p_end; ++n) {
                        const uint8_t ci = d[p++];
                        img.set_pixel(x++, y, pal[ci].r, pal[ci].g, pal[ci].b, 255);
                    }
                }
            } else {
                // 0x81–0xFF: skip (cmd-0x80) transparent pixels
                x += cmd - 0x80;
            }
        }

        result.frames.push_back(std::move(img));
    }

    return result;
}

// ---------------------------------------------------------------------------
// save_icn
// ---------------------------------------------------------------------------

void save_icn(const IcnFile& icn, const std::string& out_dir) {
    fs::create_directories(out_dir);

    const int n = static_cast<int>(icn.headers.size());
    for (int i = 0; i < n; ++i) {
        if (i >= static_cast<int>(icn.frames.size())) break;
        const auto& img = icn.frames[i];
        if (img.width == 0 || img.height == 0) continue;

        char name[32];
        std::snprintf(name, sizeof(name), "%04d.png", i);
        save_png(img, out_dir + "/" + name);
    }

    // Write spec.xml
    std::ofstream xml(out_dir + "/spec.xml");
    if (!xml) throw std::runtime_error("Cannot write spec.xml in " + out_dir);
    xml << "<icn count=\"" << n << "\">\n";
    for (int i = 0; i < n; ++i) {
        const auto& h = icn.headers[i];
        char fname[32];
        std::snprintf(fname, sizeof(fname), "%04d.png", i);
        xml << "  <sprite id=\"" << i << "\""
            << " file=\"" << fname << "\""
            << " offsetX=\"" << h.offset_x << "\""
            << " offsetY=\"" << h.offset_y << "\""
            << " width=\""   << h.width    << "\""
            << " height=\""  << h.height   << "\""
            << "/>\n";
    }
    xml << "</icn>\n";
}

} // namespace homm1
