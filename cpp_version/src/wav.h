#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace homm1 {

// Convert raw .82m PCM data to a standard WAV file at out_path.
//
// The .82m format is raw PCM audio.  HoMM1 AGG files carry no header;
// the observed defaults are 11025 Hz / mono / 16-bit signed PCM.
//
// If the data begins with the four-byte magic "82M " an extended header
// is parsed:
//   bytes 0-3:  "82M "
//   bytes 4-7:  sample rate (u32 LE)
//   bytes 8-9:  channels    (u16 LE)
//   bytes 10-11: bits/sample (u16 LE)
//   bytes 12+:  raw PCM
//
// Falls back to defaults if the magic is absent.
void decode_82m_to_wav(const std::vector<uint8_t>& raw,
                       const std::string& out_path);

} // namespace homm1
