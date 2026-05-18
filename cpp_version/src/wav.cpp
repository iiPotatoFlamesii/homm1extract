#include "wav.h"
#include <cstring>
#include <fstream>
#include <stdexcept>

namespace homm1 {

// ---------------------------------------------------------------------------
// WAV file writer (PCM, no dependencies beyond the C++ standard library)
//
// WAV / RIFF layout:
//   "RIFF" + u32 file_size-8 + "WAVE"
//   "fmt " + u32 chunk_size(16) + u16 audio_fmt(1=PCM) + u16 channels
//           + u32 sample_rate  + u32 byte_rate
//           + u16 block_align  + u16 bits_per_sample
//   "data" + u32 data_size + <raw PCM bytes>
// ---------------------------------------------------------------------------

static void write_le16(std::vector<uint8_t>& buf, uint16_t v) {
    buf.push_back(v & 0xFF);
    buf.push_back((v >> 8) & 0xFF);
}
static void write_le32(std::vector<uint8_t>& buf, uint32_t v) {
    buf.push_back( v        & 0xFF);
    buf.push_back((v >>  8) & 0xFF);
    buf.push_back((v >> 16) & 0xFF);
    buf.push_back((v >> 24) & 0xFF);
}
static void write_fourcc(std::vector<uint8_t>& buf, const char cc[4]) {
    buf.insert(buf.end(), cc, cc + 4);
}

static std::vector<uint8_t> build_wav(const uint8_t* pcm, size_t pcm_len,
                                      uint32_t sample_rate,
                                      uint16_t channels,
                                      uint16_t bits_per_sample) {
    const uint16_t block_align  = channels * (bits_per_sample / 8);
    const uint32_t byte_rate    = sample_rate * block_align;
    const uint32_t data_size    = static_cast<uint32_t>(pcm_len);
    const uint32_t riff_size    = 4 + 8 + 16 + 8 + data_size; // "WAVE" + fmt chunk + data chunk

    std::vector<uint8_t> out;
    out.reserve(12 + 24 + 8 + pcm_len);

    // RIFF header
    write_fourcc(out, "RIFF");
    write_le32(out, riff_size);
    write_fourcc(out, "WAVE");

    // fmt chunk
    write_fourcc(out, "fmt ");
    write_le32(out, 16);           // chunk size (PCM)
    write_le16(out, 1);            // audio format: PCM
    write_le16(out, channels);
    write_le32(out, sample_rate);
    write_le32(out, byte_rate);
    write_le16(out, block_align);
    write_le16(out, bits_per_sample);

    // data chunk
    write_fourcc(out, "data");
    write_le32(out, data_size);
    out.insert(out.end(), pcm, pcm + pcm_len);

    return out;
}

// ---------------------------------------------------------------------------
// decode_82m_to_wav
// ---------------------------------------------------------------------------

void decode_82m_to_wav(const std::vector<uint8_t>& raw,
                       const std::string& out_path) {
    // HoMM1 defaults — headerless raw 16-bit mono PCM at 11025 Hz.
    uint32_t sample_rate    = 11025;
    uint16_t channels       = 1;
    uint16_t bits_per_sample = 16;
    size_t   data_offset    = 0;

    // Optional "82M " header detection
    if (raw.size() >= 12 && std::memcmp(raw.data(), "82M ", 4) == 0) {
        std::memcpy(&sample_rate,     raw.data() + 4, 4);
        std::memcpy(&channels,        raw.data() + 8, 2);
        std::memcpy(&bits_per_sample, raw.data() + 10, 2);
        data_offset = 12;
        // Note: assumes little-endian host (x86/ARM-LE), same as rest of codebase.
    }

    if (data_offset >= raw.size()) return; // nothing to write

    const std::vector<uint8_t> wav = build_wav(
        raw.data() + data_offset,
        raw.size() - data_offset,
        sample_rate, channels, bits_per_sample);

    std::ofstream f(out_path, std::ios::binary);
    if (!f) throw std::runtime_error("Cannot write WAV: " + out_path);
    if (!f.write(reinterpret_cast<const char*>(wav.data()), wav.size()))
        throw std::runtime_error("Write failed: " + out_path);
}

} // namespace homm1
