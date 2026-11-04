//! Deterministic randomness, noise and small math helpers.

/// A well-mixed 32-bit integer hash (lowbias32).
#[inline]
pub fn hash32(mut x: u32) -> u32 {
    x ^= x >> 16;
    x = x.wrapping_mul(0x7feb_352d);
    x ^= x >> 15;
    x = x.wrapping_mul(0x846c_a68b);
    x ^= x >> 16;
    x
}

/// Hash of three integers.
#[inline]
pub fn hash3(a: u32, b: u32, c: u32) -> u32 {
    hash32(a.wrapping_add(hash32(b.wrapping_add(hash32(c.wrapping_add(0x9e37_79b9))))))
}

/// Uniform random in [0, 1) from three integers.
#[inline]
pub fn rnd(a: u32, b: u32, c: u32) -> f32 {
    (hash3(a, b, c) >> 8) as f32 * (1.0 / 16_777_216.0)
}

/// Uniform random in [-1, 1).
#[inline]
pub fn rnd_s(a: u32, b: u32, c: u32) -> f32 {
    rnd(a, b, c) * 2.0 - 1.0
}

#[inline]
pub fn clamp01(x: f32) -> f32 {
    x.clamp(0.0, 1.0)
}

#[inline]
pub fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}

#[inline]
pub fn smoothstep(e0: f32, e1: f32, x: f32) -> f32 {
    if e1 <= e0 {
        return if x >= e0 { 1.0 } else { 0.0 };
    }
    let t = clamp01((x - e0) / (e1 - e0));
    t * t * (3.0 - 2.0 * t)
}

#[inline]
pub fn fract(x: f32) -> f32 {
    x - x.floor()
}

/// Seed from a user "seed" slider plus an optional time-based variation.
#[inline]
pub fn seed_of(seed: f32, extra: u32) -> u32 {
    hash32((seed.round() as i64 as u32).wrapping_mul(0x2545_f491) ^ extra)
}

/// Smooth value noise in [0, 1] on an integer lattice.
pub fn value_noise(x: f32, y: f32, seed: u32) -> f32 {
    let xi = x.floor();
    let yi = y.floor();
    let (fx, fy) = (x - xi, y - yi);
    let (ix, iy) = (xi as i32 as u32, yi as i32 as u32);
    let a = rnd(ix, iy, seed);
    let b = rnd(ix.wrapping_add(1), iy, seed);
    let c = rnd(ix, iy.wrapping_add(1), seed);
    let d = rnd(ix.wrapping_add(1), iy.wrapping_add(1), seed);
    let ux = fx * fx * (3.0 - 2.0 * fx);
    let uy = fy * fy * (3.0 - 2.0 * fy);
    lerp(lerp(a, b, ux), lerp(c, d, ux), uy)
}

/// Fractal value noise in [0, 1].
pub fn fbm(x: f32, y: f32, seed: u32, octaves: u32) -> f32 {
    let mut sum = 0.0;
    let mut amp = 0.5;
    let mut norm = 0.0;
    let (mut fx, mut fy) = (x, y);
    for o in 0..octaves.max(1) {
        sum += amp * value_noise(fx, fy, seed.wrapping_add(o * 1013));
        norm += amp;
        amp *= 0.5;
        fx = fx * 2.03 + 17.1;
        fy = fy * 2.03 - 9.7;
    }
    sum / norm
}

/// [`fbm`] with each octave's lattice corners kept between calls: neighbouring pixels share
/// cells, so a scan along a row hashes again only when it enters a new cell. Same result as
/// [`fbm`] to the bit.
pub struct FbmCache {
    seed: u32,
    octaves: u32,
    cells: [(u32, u32, [f32; 4]); 8],
    valid: [bool; 8],
}

impl FbmCache {
    pub fn new(seed: u32, octaves: u32) -> Self {
        FbmCache { seed, octaves: octaves.max(1), cells: [(0, 0, [0.0; 4]); 8], valid: [false; 8] }
    }

    pub fn fbm(&mut self, x: f32, y: f32) -> f32 {
        let mut sum = 0.0;
        let mut amp = 0.5;
        let mut norm = 0.0;
        let (mut fx, mut fy) = (x, y);
        for o in 0..self.octaves {
            let v = if (o as usize) < 8 { self.noise(o as usize, fx, fy) } else { value_noise(fx, fy, self.seed.wrapping_add(o * 1013)) };
            sum += amp * v;
            norm += amp;
            amp *= 0.5;
            fx = fx * 2.03 + 17.1;
            fy = fy * 2.03 - 9.7;
        }
        sum / norm
    }

    #[inline]
    fn noise(&mut self, o: usize, x: f32, y: f32) -> f32 {
        let xi = x.floor();
        let yi = y.floor();
        let (fx, fy) = (x - xi, y - yi);
        let (ix, iy) = (xi as i32 as u32, yi as i32 as u32);
        let cell = &mut self.cells[o];
        if !self.valid[o] || cell.0 != ix || cell.1 != iy {
            let seed = self.seed.wrapping_add(o as u32 * 1013);
            *cell = (ix, iy, [
                rnd(ix, iy, seed),
                rnd(ix.wrapping_add(1), iy, seed),
                rnd(ix, iy.wrapping_add(1), seed),
                rnd(ix.wrapping_add(1), iy.wrapping_add(1), seed),
            ]);
            self.valid[o] = true;
        }
        let [a, b, c, d] = cell.2;
        let ux = fx * fx * (3.0 - 2.0 * fx);
        let uy = fy * fy * (3.0 - 2.0 * fy);
        lerp(lerp(a, b, ux), lerp(c, d, ux), uy)
    }
}

/// `x^g` for x > 0, through log2 / exp2 series in f64 (~1e-9 relative, so the f32 result is
/// `powf`'s to the last bit or one ulp off; `g == 1` returns `x` exactly, like `powf`). Several
/// times cheaper than libm's `powf` in the wasmi interpreter.
#[inline]
pub fn pow_fast(x: f32, g: f32) -> f32 {
    if g == 1.0 {
        return x;
    }
    if !(x >= 1e-30 && x < 1e30) {
        return x.powf(g);
    }
    // x = m · 2^e with m in [√½, √2).
    let bits = (x as f64).to_bits();
    let mut e = ((bits >> 52) & 0x7ff) as i64 - 1023;
    let mut m = f64::from_bits((bits & 0x000f_ffff_ffff_ffff) | 0x3ff0_0000_0000_0000);
    if m > std::f64::consts::SQRT_2 {
        m *= 0.5;
        e += 1;
    }
    // ln m = 2·atanh(t), t = (m−1)/(m+1), |t| < 0.172.
    let t = (m - 1.0) / (m + 1.0);
    let t2 = t * t;
    let ln_m = 2.0 * t * (1.0 + t2 * (1.0 / 3.0 + t2 * (1.0 / 5.0 + t2 * (1.0 / 7.0 + t2 * (1.0 / 9.0 + t2 * (1.0 / 11.0))))));
    let y = g as f64 * (e as f64 + ln_m * std::f64::consts::LOG2_E);
    // 2^y = 2^n · e^(f·ln2), |f| ≤ ½. n = y.round(), from the native trunc (libm's round is
    // software in WebAssembly): y − trunc(y) is exact, so this is the same value.
    let t = y.trunc();
    let d = y - t;
    let n = if d >= 0.5 { t + 1.0 } else if d <= -0.5 { t - 1.0 } else { t };
    let r = (y - n) * std::f64::consts::LN_2;
    let p = 1.0 + r * (1.0 + r * (0.5 + r * (1.0 / 6.0 + r * (1.0 / 24.0 + r * (1.0 / 120.0 + r * (1.0 / 720.0 + r * (1.0 / 5040.0 + r * (1.0 / 40320.0))))))));
    (p * f64::from_bits(((n as i64 + 1023) as u64) << 52)) as f32
}

/// `x^g` for one fixed exponent through two small tables: x = m · 2^e, so x^g = m^g · 2^(e·g),
/// m^g interpolated linearly between 4096 steps of [1, 2], 2^(e·g) exact per exponent. Relative
/// error below 6e-7 (a few f32 ulps), about ten times cheaper than [`pow_fast`] in
/// the wasmi interpreter: for per-pixel gammas where a last-bit difference is invisible.
pub struct PowTable {
    g: f32,
    mant: Vec<f32>,
    exp2: Vec<f32>,
}

impl PowTable {
    const BITS: u32 = 12;
    const EMIN: i32 = -100; // 2^-100 < 1e-30: smaller inputs go to powf

    pub fn new(g: f32) -> Self {
        let n = 1usize << Self::BITS;
        let mant = (0..=n).map(|i| (1.0 + i as f64 / n as f64).powf(g as f64) as f32).collect();
        let exp2 = (Self::EMIN..=100).map(|e| (e as f64 * g as f64).exp2() as f32).collect();
        PowTable { g, mant, exp2 }
    }

    #[inline]
    pub fn pow(&self, x: f32) -> f32 {
        if self.g == 1.0 {
            return x;
        }
        if !(x >= 1e-30 && x < 1e30) {
            return x.powf(self.g);
        }
        let bits = x.to_bits();
        let e = ((bits >> 23) & 0xff) as i32 - 127;
        let frac = bits & 0x7f_ffff;
        let i = (frac >> (23 - Self::BITS)) as usize;
        let t = (frac & ((1 << (23 - Self::BITS)) - 1)) as f32 * (1.0 / (1u32 << (23 - Self::BITS)) as f32);
        // SAFETY: i < 2^BITS and mant has 2^BITS + 1 entries; 1e-30 ≤ x < 1e30 keeps e in
        // [EMIN, 100], the range of exp2.
        unsafe {
            let a = *self.mant.get_unchecked(i);
            let b = *self.mant.get_unchecked(i + 1);
            (a + (b - a) * t) * *self.exp2.get_unchecked((e - Self::EMIN) as usize)
        }
    }
}

/// A direction vector from an After Effects style angle (0 = up, clockwise, y down).
#[inline]
pub fn dir_from_angle(rad: f32) -> [f32; 2] {
    [rad.sin(), -rad.cos()]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pow_fast_matches_powf_within_one_ulp() {
        let mut worst = 0i64;
        for g in [0.01f32, 0.3, 0.7, 1.0 / 3.0, 1.0 / 2.4, 1.0, 1.5, 2.4, 3.0, 7.0] {
            for i in 1..200_000u32 {
                let x = i as f32 / 100_000.0; // 0 … 2
                let (a, b) = (pow_fast(x, g), x.powf(g));
                worst = worst.max((a.to_bits() as i64 - b.to_bits() as i64).abs());
            }
        }
        assert!(worst <= 1, "worst {worst} ulp");
    }

    #[test]
    fn pow_table_is_within_6e7_of_powf() {
        for g in [0.01f32, 0.3, 0.7, 1.0 / 2.4, 1.5, 2.4, 7.0] {
            let t = PowTable::new(g);
            let mut worst = 0.0f64;
            for i in 1..400_000u32 {
                for x in [i as f32 / 200_000.0, i as f32 * 1e-6, i as f32 * 37.0] {
                    let (a, b) = (t.pow(x) as f64, (x as f64).powf(g as f64));
                    if b > 1e37 {
                        continue; // beyond f32
                    }
                    worst = worst.max((a - b).abs() / b.max(1e-30));
                }
            }
            assert!(worst < 6e-7, "g {g}: relative error {worst}");
        }
        assert_eq!(PowTable::new(1.0).pow(0.37), 0.37);
        assert_eq!(PowTable::new(0.7).pow(0.0), 0.0);
    }

    #[test]
    fn fbm_cache_matches_fbm_to_the_bit() {
        for (sc, oct) in [(200.0f32, 4u32), (7.0, 3), (0.9, 2), (31.0, 9)] {
            let mut c = FbmCache::new(0xABCD, oct);
            for y in [0.0f32, 3.0, 517.0] {
                for x in 0..700 {
                    let (u, v) = (x as f32 / sc + 0.37, y / sc - 1.3);
                    assert_eq!(c.fbm(u, v).to_bits(), fbm(u, v, 0xABCD, oct).to_bits(), "sc {sc} oct {oct} x {x}");
                }
            }
        }
    }
}
