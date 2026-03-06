/**
 * Security Constants & SHA-256 Implementation
 *
 * Provides client-side password hashing for secure authentication.
 * Uses Web Crypto API when available, falls back to pure JS implementation.
 */

/**
 * Application-level salt for client-side password hashing.
 * MUST match the backend APP_SALT in auth_local.py
 */
export const APP_SALT = 'PathLab2024SecureSalt'

/**
 * Pure JavaScript SHA-256 implementation for non-secure contexts.
 * Used when crypto.subtle is not available (HTTP non-localhost).
 */
function sha256Fallback(message: string): string {
  // SHA-256 constants
  const K: number[] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ]

  // Initial hash values
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19

  // Pre-processing: convert to bytes
  const bytes: number[] = []
  for (let i = 0; i < message.length; i++) {
    const code = message.charCodeAt(i)
    if (code < 0x80) bytes.push(code)
    else if (code < 0x800) { bytes.push(0xc0 | (code >> 6)); bytes.push(0x80 | (code & 0x3f)) }
    else { bytes.push(0xe0 | (code >> 12)); bytes.push(0x80 | ((code >> 6) & 0x3f)); bytes.push(0x80 | (code & 0x3f)) }
  }

  const bitLength = bytes.length * 8
  bytes.push(0x80)
  while ((bytes.length % 64) !== 56) bytes.push(0)

  // Append length as 64-bit big-endian
  // Note: JavaScript's >>> clamps the shift amount mod 32, so we can't use
  // a loop with shifts > 31. Split into high/low 32-bit words explicitly.
  const lenHi = Math.floor(bitLength / 0x100000000) >>> 0
  const lenLo = bitLength >>> 0
  bytes.push((lenHi >>> 24) & 0xff, (lenHi >>> 16) & 0xff, (lenHi >>> 8) & 0xff, lenHi & 0xff)
  bytes.push((lenLo >>> 24) & 0xff, (lenLo >>> 16) & 0xff, (lenLo >>> 8) & 0xff, lenLo & 0xff)

  // Process each 64-byte chunk
  for (let offset = 0; offset < bytes.length; offset += 64) {
    const w: number[] = new Array(64)
    for (let i = 0; i < 16; i++) {
      w[i] = (bytes[offset + i * 4] << 24) | (bytes[offset + i * 4 + 1] << 16) |
        (bytes[offset + i * 4 + 2] << 8) | bytes[offset + i * 4 + 3]
    }
    for (let i = 16; i < 64; i++) {
      const s0 = ((w[i-15] >>> 7) | (w[i-15] << 25)) ^ ((w[i-15] >>> 18) | (w[i-15] << 14)) ^ (w[i-15] >>> 3)
      const s1 = ((w[i-2] >>> 17) | (w[i-2] << 15)) ^ ((w[i-2] >>> 19) | (w[i-2] << 13)) ^ (w[i-2] >>> 10)
      w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0
    }

    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
      const ch = (e & f) ^ (~e & g)
      const temp1 = (h + S1 + ch + K[i] + w[i]) | 0
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const temp2 = (S0 + maj) | 0

      h = g; g = f; f = e; e = (d + temp1) | 0; d = c; c = b; b = a; a = (temp1 + temp2) | 0
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0
    h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0
  }

  const hex = (n: number): string => {
    const s = (n >>> 0).toString(16)
    return '00000000'.slice(s.length) + s
  }
  return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4) + hex(h5) + hex(h6) + hex(h7)
}

/**
 * Compute SHA-256 hash of a message.
 * Uses Web Crypto API when available (secure contexts), falls back to pure JS implementation.
 */
export async function sha256(message: string): Promise<string> {
  // Try Web Crypto API first (available in secure contexts: HTTPS, localhost, Electron)
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    try {
      const encoder = new TextEncoder()
      const data = encoder.encode(message)
      const hashBuffer = await crypto.subtle.digest('SHA-256', data)
      const hashArray = Array.from(new Uint8Array(hashBuffer))
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
    } catch {
      // Fall through to JS implementation
    }
  }
  // Fallback: pure JavaScript SHA-256 implementation
  return sha256Fallback(message)
}

