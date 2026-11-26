// Peak per bucket on a fixed dB scale: -60 dBFS -> 0, 0 dBFS -> 1 (every track shares the scale).
export function peaksDb(samples: Float32Array, buckets: number): Float32Array {
  const out = new Float32Array(buckets);
  const size = samples.length / buckets;
  for (let i = 0; i < buckets; i++) {
    let peak = 0;
    const end = Math.max(Math.floor((i + 1) * size), Math.floor(i * size) + 1);
    for (let j = Math.floor(i * size); j < end && j < samples.length; j++) peak = Math.max(peak, Math.abs(samples[j]));
    out[i] = peak > 0 ? Math.min(1, Math.max(0, (20 * Math.log10(peak) + 60) / 60)) : 0;
  }
  return out;
}
