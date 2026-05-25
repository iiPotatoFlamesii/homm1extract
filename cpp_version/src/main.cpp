#include "agg.h"
#include "atk.h"
#include "bkg.h"
#include "bmp.h"
#include "icn.h"
#include "image.h"
#include "palette.h"
#include "std.h"
#include "til.h"
#include "wav.h"

#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace fs = std::filesystem;

// Upper-case a string, return by value.
static std::string to_upper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), ::toupper);
    return s;
}

// Return the extension of a DOS filename (upper-case, including the dot).
static std::string ext_of(const std::string& name) {
    const auto dot = name.rfind('.');
    if (dot == std::string::npos) return {};
    return to_upper(name.substr(dot));
}

// Stem: filename without extension.
static std::string stem_of(const std::string& name) {
    const auto dot = name.find_last_of('.');
    if (dot == std::string::npos) return name;
    return name.substr(0, dot);
}

// Save raw bytes verbatim to disk.
static void save_raw(const std::vector<uint8_t>& data, const std::string& path) {
    std::ofstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot write: " + path);
    f.write(reinterpret_cast<const char*>(data.data()), data.size());
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: homm1_extract <path/to/heroes.agg> [output_dir]\n";
        return 1;
    }

    const std::string agg_path = argv[1];
    const std::string out_root = (argc >= 3)
        ? argv[2]
        : fs::path(agg_path).stem().string();

    // -----------------------------------------------------------------------
    // Load archive
    // -----------------------------------------------------------------------
    homm1::AggArchive arc;
    try {
        std::cout << "Loading " << agg_path << " ...\n";
        arc = homm1::load_agg(agg_path);
        std::cout << "  " << arc.entries.size() << " file(s) found.\n";
    } catch (const std::exception& ex) {
        std::cerr << "ERROR: " << ex.what() << "\n";
        return 1;
    }

    fs::create_directories(out_root);

    // -----------------------------------------------------------------------
    // Load palette first (needed for all image decoding)
    // -----------------------------------------------------------------------
    homm1::Palette palette;
    bool have_palette = false;

    for (const auto& e : arc.entries) {
        if (ext_of(e.name) == ".PAL") {
            try {
                std::cout << "  Loading palette from '" << e.name << "' ...\n";
                const auto raw = arc.get(e.name);
                palette = homm1::load_palette(raw);
                have_palette = true;

                const std::string swatch = out_root + "/palette_swatch.png";
                homm1::save_palette_swatch(palette, swatch);
                std::cout << "  Palette swatch -> " << swatch << "\n";
            } catch (const std::exception& ex) {
                std::cerr << "  WARNING: palette load failed: " << ex.what() << "\n";
            }
            break; // both PAL copies are identical in HoMM1
        }
    }

    if (!have_palette) {
        std::cerr << "WARNING: no .PAL file found — using greyscale fallback.\n";
        for (int i = 0; i < 256; ++i)
            palette[i] = {static_cast<uint8_t>(i),
                          static_cast<uint8_t>(i),
                          static_cast<uint8_t>(i)};
    }

    // -----------------------------------------------------------------------
    // Extract all files
    // -----------------------------------------------------------------------
    int n_ok = 0, n_err = 0;

    for (const auto& e : arc.entries) {
        if (e.name.empty()) continue;

        const std::string ext  = ext_of(e.name);
        const std::string stem = stem_of(e.name);

        try {
            // ----------------------------------------------------------------
            // ICN — generic sprites (UI, cursors, portraits, etc.)
            // ----------------------------------------------------------------
            if (ext == ".ICN") {
                const std::string dir = out_root + "/" + stem;
                std::cout << "  ICN  " << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                auto icn = homm1::decode_icn(raw, palette, stem);
                homm1::save_icn(icn, dir);

            // ----------------------------------------------------------------
            // STD — creature standing/attack animations with compositing
            // ----------------------------------------------------------------
            } else if (ext == ".STD") {
                const std::string dir = out_root + "/" + stem + ".std";
                std::cout << "  STD  " << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                homm1::decode_and_save_std(raw, palette, dir, stem);

            // ----------------------------------------------------------------
            // WLK — walk cycle animation  (plain ICN frames, no compositing)
            // WIP — death/wipe animation  (plain ICN frames, no compositing)
            // ----------------------------------------------------------------
            } else if (ext == ".WLK" || ext == ".WIP") {
                const std::string stemExt = stem +
                                            (ext == ".WLK" ? ".wlk" : ".wip");
                const std::string dir = out_root + "/" + stemExt;
                std::cout << "  " << ext.substr(1) << "  "
                          << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                auto icn = homm1::decode_icn(raw, palette, stemExt);
                homm1::save_icn(icn, dir);

            // ----------------------------------------------------------------
            // ATK — ranged attack animation with compositing + projectiles
            // ----------------------------------------------------------------
            } else if (ext == ".ATK") {
                const std::string dir = out_root + "/" + stem + ".atk";
                std::cout << "  ATK  " << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                homm1::decode_and_save_atk(raw, palette, dir, stem);

            // ----------------------------------------------------------------
            // OBJ — battle scene object sprites  (plain ICN encoding)
            // XTL — battle hex tile sprites       (plain ICN encoding)
            // ----------------------------------------------------------------
            } else if (ext == ".OBJ" || ext == ".XTL") {
                const std::string tag = (ext == ".OBJ") ? ".obj" : ".xtl";
                const std::string dir = out_root + "/" + stem + tag;
                std::cout << "  " << ext.substr(1) << "  "
                          << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                auto icn = homm1::decode_icn(raw, palette, stem);
                homm1::save_icn(icn, dir);

            // ----------------------------------------------------------------
            // BKG — battle background sky strip
            // ----------------------------------------------------------------
            } else if (ext == ".BKG") {
                const std::string out_path = out_root + "/" + stem + "_bkg.png";
                std::cout << "  BKG  " << e.name << "  ->  " << out_path << "\n";
                const auto raw = arc.get(e.name);
                const auto img = homm1::decode_bkg(raw, palette);
                homm1::save_png(img, out_path);

            // ----------------------------------------------------------------
            // TIL — map terrain tiles
            // ----------------------------------------------------------------
            } else if (ext == ".TIL") {
                const std::string dir = out_root + "/" + stem;
                std::cout << "  TIL  " << e.name << "  ->  " << dir << "/\n";
                const auto raw = arc.get(e.name);
                auto til = homm1::decode_til(raw, palette);
                homm1::save_til(til, dir);

            // ----------------------------------------------------------------
            // BMP — custom HoMM palette-indexed background images
            // ----------------------------------------------------------------
            } else if (ext == ".BMP") {
                const std::string out_path = out_root + "/" + stem + ".png";
                std::cout << "  BMP  " << e.name << "  ->  " << out_path << "\n";
                const auto raw = arc.get(e.name);
                auto img = homm1::decode_bmp(raw, palette);
                homm1::save_png(img, out_path);

            // ----------------------------------------------------------------
            // 82M — raw PCM audio, converted to WAV
            // ----------------------------------------------------------------
            } else if (ext == ".82M") {
                const std::string out_path = out_root + "/" + stem + ".wav";
                std::cout << "  SND  " << e.name << "  ->  " << out_path << "\n";
                const auto raw = arc.get(e.name);
                try {
                    homm1::decode_82m_to_wav(raw, out_path);
                } catch (const std::exception& wav_ex) {
                    // Fallback: save verbatim so nothing is lost.
                    std::cerr << "    WARNING: WAV conversion failed (" << wav_ex.what()
                              << ") — saving raw bytes instead.\n";
                    save_raw(raw, out_root + "/" + e.name);
                }

            // ----------------------------------------------------------------
            // PAL — palette file (save verbatim for reference)
            // ----------------------------------------------------------------
            } else if (ext == ".PAL") {
                std::cout << "  PAL  " << e.name << "  ->  "
                          << out_root + "/" + e.name << "\n";
                save_raw(arc.get(e.name), out_root + "/" + e.name);

            // ----------------------------------------------------------------
            // Everything else: BIN, MAP, MSE, TOD, etc. — save verbatim.
            // ----------------------------------------------------------------
            } else {
                const std::string out_path = out_root + "/" + e.name;
                std::cout << "  RAW  " << e.name << "  ->  " << out_path << "\n";
                save_raw(arc.get(e.name), out_path);
            }

            ++n_ok;

        } catch (const std::exception& ex) {
            std::cerr << "  ERROR processing '" << e.name << "': " << ex.what() << "\n";
            ++n_err;
        }
    }

    std::cout << "\nDone. "
              << n_ok  << " file(s) extracted"
              << (n_err ? ", " + std::to_string(n_err) + " error(s)" : "")
              << ". Output in '" << out_root << "/'\n";

    return n_err ? 1 : 0;
}
