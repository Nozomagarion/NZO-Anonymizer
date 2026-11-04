//! Image helpers on `[f32; 4]` and `f32` planes (row-major, `w * h`).

/// Clamped pixel fetch.
#[inline]
pub fn at(px: &[[f32; 4]], w: usize, h: usize, x: i32, y: i32) -> [f32; 4] {
    let x = x.clamp(0, w as i32 - 1) as usize;
    let y = y.clamp(0, h as i32 - 1) as usize;
    px[y * w + x]
}

/// Clamped scalar fetch.
#[inline]
pub fn at1(p: &[f32], w: usize, h: usize, x: i32, y: i32) -> f32 {
    let x = x.clamp(0, w as i32 - 1) as usize;
    let y = y.clamp(0, h as i32 - 1) as usize;
    p[y * w + x]
}

/// Bilinear sample with clamped edges (pixel centres at integer + 0.5).
pub fn bilinear(px: &[[f32; 4]], w: usize, h: usize, x: f32, y: f32) -> [f32; 4] {
    let fx = x - 0.5;
    let fy = y - 0.5;
    let x0 = fx.floor();
    let y0 = fy.floor();
    let tx = fx - x0;
    let ty = fy - y0;
    let (xi, yi) = (x0 as i32, y0 as i32);
    let (a, b, c, d) = if xi >= 0 && yi >= 0 && ((xi + 1) as usize) < w && ((yi + 1) as usize) < h {
        // Inside: the four taps without clamping (the same pixels `at` returns).
        let i = yi as usize * w + xi as usize;
        (px[i], px[i + 1], px[i + w], px[i + w + 1])
    } else {
        (at(px, w, h, xi, yi), at(px, w, h, xi + 1, yi), at(px, w, h, xi, yi + 1), at(px, w, h, xi + 1, yi + 1))
    };
    let mut o = [0.0; 4];
    for k in 0..4 {
        let top = a[k] + (b[k] - a[k]) * tx;
        let bot = c[k] + (d[k] - c[k]) * tx;
        o[k] = top + (bot - top) * ty;
    }
    o
}

/// Bilinear sample of a scalar plane.
pub fn bilinear1(p: &[f32], w: usize, h: usize, x: f32, y: f32) -> f32 {
    let fx = x - 0.5;
    let fy = y - 0.5;
    let x0 = fx.floor();
    let y0 = fy.floor();
    let tx = fx - x0;
    let ty = fy - y0;
    let (xi, yi) = (x0 as i32, y0 as i32);
    let (a, b, c, d) = if xi >= 0 && yi >= 0 && ((xi + 1) as usize) < w && ((yi + 1) as usize) < h {
        let i = yi as usize * w + xi as usize;
        (p[i], p[i + 1], p[i + w], p[i + w + 1])
    } else {
        (at1(p, w, h, xi, yi), at1(p, w, h, xi + 1, yi), at1(p, w, h, xi, yi + 1), at1(p, w, h, xi + 1, yi + 1))
    };
    let top = a + (b - a) * tx;
    let bot = c + (d - c) * tx;
    top + (bot - top) * ty
}

/// Nearest-neighbour sample with clamped edges.
#[inline]
pub fn nearest(px: &[[f32; 4]], w: usize, h: usize, x: f32, y: f32) -> [f32; 4] {
    at(px, w, h, x.floor() as i32, y.floor() as i32)
}

/// One horizontal box-blur pass of radius `r` over a scalar plane (edges clamped).
fn box_h(src: &[f32], dst: &mut [f32], w: usize, h: usize, r: usize) {
    let norm = 1.0 / (2 * r + 1) as f32;
    let wi = w as i32;
    // x in [lo, hi): both window ends stay inside the row (no clamping; same sums).
    let lo = r.min(w);
    let hi = (w.saturating_sub(r + 1)).max(lo);
    for y in 0..h {
        let row = &src[y * w..(y + 1) * w];
        let out = &mut dst[y * w..(y + 1) * w];
        let mut acc = 0.0;
        for k in -(r as i32)..=(r as i32) {
            acc += row[k.clamp(0, wi - 1) as usize];
        }
        let step = |x: usize, acc: &mut f32, out: &mut [f32]| {
            out[x] = *acc * norm;
            let add = (x as i32 + r as i32 + 1).min(wi - 1) as usize;
            let sub = (x as i32 - r as i32).max(0) as usize;
            *acc += row[add] - row[sub];
        };
        for x in 0..lo {
            step(x, &mut acc, out);
        }
        if hi > lo {
            for ((o, add), sub) in out[lo..hi].iter_mut().zip(&row[lo + r + 1..]).zip(&row[lo - r..]) {
                *o = acc * norm;
                acc += add - sub;
            }
        }
        for x in hi..w {
            step(x, &mut acc, out);
        }
    }
}

/// One vertical box-blur pass.
fn box_v(src: &[f32], dst: &mut [f32], w: usize, h: usize, r: usize) {
    let norm = 1.0 / (2 * r + 1) as f32;
    let hi = h as i32;
    let mut acc = vec![0.0f32; w];
    for k in -(r as i32)..=(r as i32) {
        let y = k.clamp(0, hi - 1) as usize;
        for (a, s) in acc.iter_mut().zip(&src[y * w..(y + 1) * w]) {
            *a += s;
        }
    }
    for y in 0..h {
        let add = (y as i32 + r as i32 + 1).min(hi - 1) as usize;
        let sub = (y as i32 - r as i32).max(0) as usize;
        let (ar, sr) = (&src[add * w..(add + 1) * w], &src[sub * w..(sub + 1) * w]);
        for (((d, a), p), m) in dst[y * w..(y + 1) * w].iter_mut().zip(acc.iter_mut()).zip(ar).zip(sr) {
            *d = *a * norm;
            *a += p - m;
        }
    }
}

/// Approximate Gaussian blur of a scalar plane: `passes` box blurs whose combined spread is
/// about `radius` pixels. Radius < 0.5 does nothing.
pub fn blur1(p: &mut [f32], w: usize, h: usize, radius: f32, passes: u32) {
    if radius < 0.5 || w == 0 || h == 0 {
        return;
    }
    let passes = passes.max(1);
    let r = ((radius / (passes as f32).sqrt()).round() as usize).max(1);
    let mut tmp = vec![0.0f32; w * h];
    for _ in 0..passes {
        box_h(p, &mut tmp, w, h, r);
        box_v(&tmp, p, w, h, r);
    }
}

/// [`box_h`] on the first `CH` channels of an RGBA image at once (each channel gets the same sums
/// in the same order as on its own plane); with `CH` = 3 the alpha is copied through.
fn box_h4<const CH: usize>(src: &[[f32; 4]], dst: &mut [[f32; 4]], w: usize, h: usize, r: usize) {
    let norm = 1.0 / (2 * r + 1) as f32;
    let wi = w as i32;
    let lo = r.min(w);
    let hi = (w.saturating_sub(r + 1)).max(lo);
    for y in 0..h {
        let row = &src[y * w..(y + 1) * w];
        let out = &mut dst[y * w..(y + 1) * w];
        let (mut a0, mut a1, mut a2, mut a3) = (0.0f32, 0.0f32, 0.0f32, 0.0f32);
        for k in -(r as i32)..=(r as i32) {
            let s = row[k.clamp(0, wi - 1) as usize];
            a0 += s[0];
            a1 += s[1];
            a2 += s[2];
            if CH == 4 {
                a3 += s[3];
            }
        }
        let emit = |o: &mut [f32; 4], own: &[f32; 4], add: &[f32; 4], sub: &[f32; 4], a0: &mut f32, a1: &mut f32, a2: &mut f32, a3: &mut f32| {
            *o = [*a0 * norm, *a1 * norm, *a2 * norm, if CH == 4 { *a3 * norm } else { own[3] }];
            *a0 += add[0] - sub[0];
            *a1 += add[1] - sub[1];
            *a2 += add[2] - sub[2];
            if CH == 4 {
                *a3 += add[3] - sub[3];
            }
        };
        for x in 0..lo {
            let add = (x as i32 + r as i32 + 1).min(wi - 1) as usize;
            let sub = (x as i32 - r as i32).max(0) as usize;
            emit(&mut out[x], &row[x], &row[add], &row[sub], &mut a0, &mut a1, &mut a2, &mut a3);
        }
        if hi > lo {
            for (((o, own), add), sub) in out[lo..hi].iter_mut().zip(&row[lo..hi]).zip(&row[lo + r + 1..]).zip(&row[lo - r..]) {
                emit(o, own, add, sub, &mut a0, &mut a1, &mut a2, &mut a3);
            }
        }
        for x in hi..w {
            let add = (x as i32 + r as i32 + 1).min(wi - 1) as usize;
            let sub = (x as i32 - r as i32).max(0) as usize;
            emit(&mut out[x], &row[x], &row[add], &row[sub], &mut a0, &mut a1, &mut a2, &mut a3);
        }
    }
}

/// [`box_v`] on the first `CH` channels of an RGBA image at once (alpha copied when `CH` = 3).
fn box_v4<const CH: usize>(src: &[[f32; 4]], dst: &mut [[f32; 4]], w: usize, h: usize, r: usize) {
    let norm = 1.0 / (2 * r + 1) as f32;
    let hi = h as i32;
    let mut acc = vec![[0.0f32; 4]; w];
    for k in -(r as i32)..=(r as i32) {
        let y = k.clamp(0, hi - 1) as usize;
        for (a, s) in acc.iter_mut().zip(&src[y * w..(y + 1) * w]) {
            a[0] += s[0];
            a[1] += s[1];
            a[2] += s[2];
            if CH == 4 {
                a[3] += s[3];
            }
        }
    }
    for y in 0..h {
        let add = (y as i32 + r as i32 + 1).min(hi - 1) as usize;
        let sub = (y as i32 - r as i32).max(0) as usize;
        let (ar, sr, own) = (&src[add * w..(add + 1) * w], &src[sub * w..(sub + 1) * w], &src[y * w..(y + 1) * w]);
        for ((((d, a), p), m), o) in dst[y * w..(y + 1) * w].iter_mut().zip(acc.iter_mut()).zip(ar).zip(sr).zip(own) {
            *d = [a[0] * norm, a[1] * norm, a[2] * norm, if CH == 4 { a[3] * norm } else { o[3] }];
            a[0] += p[0] - m[0];
            a[1] += p[1] - m[1];
            a[2] += p[2] - m[2];
            if CH == 4 {
                a[3] += p[3] - m[3];
            }
        }
    }
}

/// [`blur1`] on the first `CH` channels of an RGBA image, all channels in each pass.
fn blur_rgba<const CH: usize>(px: &mut [[f32; 4]], w: usize, h: usize, radius: f32, passes: u32) {
    if radius < 0.5 || w == 0 || h == 0 {
        return;
    }
    let passes = passes.max(1);
    let r = ((radius / (passes as f32).sqrt()).round() as usize).max(1);
    let mut tmp = vec![[0.0f32; 4]; w * h];
    for _ in 0..passes {
        box_h4::<CH>(px, &mut tmp, w, h, r);
        box_v4::<CH>(&tmp, px, w, h, r);
    }
}

/// [`blur1`] on each of the four channels of an RGBA image (the same values as blurring each
/// channel's plane on its own).
pub fn blur4(px: &mut [[f32; 4]], w: usize, h: usize, radius: f32, passes: u32) {
    blur_rgba::<4>(px, w, h, radius, passes);
}

/// [`blur1`] on the three colour channels only.
pub fn blur3(px: &mut [[f32; 4]], w: usize, h: usize, radius: f32, passes: u32) {
    blur_rgba::<3>(px, w, h, radius, passes);
}

/// Box blurs of the three colour channels, one H + V pass per entry of `radii` (0 = skipped),
/// alpha copied through: [`blur3`] with a chosen radius per pass, to match a blur's spread on
/// a reduced image.
pub fn blur3_radii(px: &mut [[f32; 4]], w: usize, h: usize, radii: &[usize]) {
    if w == 0 || h == 0 || radii.iter().all(|&r| r == 0) {
        return;
    }
    let mut tmp = vec![[0.0f32; 4]; w * h];
    for &r in radii.iter().filter(|&&r| r > 0) {
        box_h4::<3>(px, &mut tmp, w, h, r);
        box_v4::<3>(&tmp, px, w, h, r);
    }
}

/// Mixes the processed frame `out` back towards the original `orig` (both premultiplied).
pub fn mix_back(out: &mut [[f32; 4]], orig: &[[f32; 4]], amount: f32) {
    let t = amount.clamp(0.0, 1.0);
    if t >= 1.0 {
        return;
    }
    for (o, s) in out.iter_mut().zip(orig.iter()) {
        for k in 0..4 {
            o[k] = s[k] + (o[k] - s[k]) * t;
        }
    }
}

/// Luminance plane of a premultiplied image, computed on straight colours.
pub fn luma_plane(px: &[[f32; 4]]) -> Vec<f32> {
    px.iter()
        .map(|p| {
            let c = crate::color::unpremul(*p);
            crate::color::luma(&c)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The box passes before their unclamped fast paths (2026-10-31), the bit-exact reference.
    fn box_h_ref(src: &[f32], dst: &mut [f32], w: usize, h: usize, r: usize) {
        let norm = 1.0 / (2 * r + 1) as f32;
        let wi = w as i32;
        for y in 0..h {
            let row = &src[y * w..(y + 1) * w];
            let mut acc = 0.0;
            for k in -(r as i32)..=(r as i32) {
                acc += row[k.clamp(0, wi - 1) as usize];
            }
            for x in 0..w {
                dst[y * w + x] = acc * norm;
                acc += row[(x as i32 + r as i32 + 1).min(wi - 1) as usize] - row[(x as i32 - r as i32).max(0) as usize];
            }
        }
    }

    fn box_v_ref(src: &[f32], dst: &mut [f32], w: usize, h: usize, r: usize) {
        let norm = 1.0 / (2 * r + 1) as f32;
        let hi = h as i32;
        let mut acc = vec![0.0f32; w];
        for k in -(r as i32)..=(r as i32) {
            let y = k.clamp(0, hi - 1) as usize;
            for x in 0..w {
                acc[x] += src[y * w + x];
            }
        }
        for y in 0..h {
            let add = (y as i32 + r as i32 + 1).min(hi - 1) as usize;
            let sub = (y as i32 - r as i32).max(0) as usize;
            for x in 0..w {
                dst[y * w + x] = acc[x] * norm;
                acc[x] += src[add * w + x] - src[sub * w + x];
            }
        }
    }

    #[test]
    fn rgba_blurs_match_per_channel_blur1_to_the_bit() {
        for (w, h) in [(1usize, 1usize), (3, 8), (40, 23), (97, 61)] {
            let src: Vec<[f32; 4]> = (0..w * h).map(|i| [0, 1, 2, 3].map(|k| crate::math::rnd(i as u32, k, 9))).collect();
            for (radius, passes) in [(0.7f32, 1u32), (3.0, 2), (12.0, 3), (60.0, 3)] {
                let (mut a4, mut a3) = (src.clone(), src.clone());
                blur4(&mut a4, w, h, radius, passes);
                blur3(&mut a3, w, h, radius, passes);
                for c in 0..4 {
                    let mut plane: Vec<f32> = src.iter().map(|p| p[c]).collect();
                    blur1(&mut plane, w, h, radius, passes);
                    assert!(plane.iter().zip(&a4).all(|(p, q)| p.to_bits() == q[c].to_bits()), "blur4 {w}x{h} r{radius} c{c}");
                    let want: Vec<f32> = if c == 3 { src.iter().map(|p| p[3]).collect() } else { plane };
                    assert!(want.iter().zip(&a3).all(|(p, q)| p.to_bits() == q[c].to_bits()), "blur3 {w}x{h} r{radius} c{c}");
                }
            }
        }
    }

    #[test]
    fn box_passes_match_the_clamped_reference_to_the_bit() {
        for (w, h) in [(1usize, 1usize), (2, 5), (7, 3), (40, 23), (97, 61)] {
            let src: Vec<f32> = (0..w * h).map(|i| crate::math::rnd(i as u32, 7, 3)).collect();
            for r in [1usize, 2, 3, 5, 19, 48, 120] {
                let (mut a, mut b) = (vec![0.0; w * h], vec![0.0; w * h]);
                box_h(&src, &mut a, w, h, r);
                box_h_ref(&src, &mut b, w, h, r);
                assert!(a.iter().zip(&b).all(|(p, q)| p.to_bits() == q.to_bits()), "h {w}x{h} r{r}");
                box_v(&src, &mut a, w, h, r);
                box_v_ref(&src, &mut b, w, h, r);
                assert!(a.iter().zip(&b).all(|(p, q)| p.to_bits() == q.to_bits()), "v {w}x{h} r{r}");
            }
        }
    }
}

/// Sobel gradient magnitude and direction of a scalar plane: (gx, gy) per pixel.
pub fn sobel(p: &[f32], w: usize, h: usize) -> Vec<[f32; 2]> {
    let mut out = vec![[0.0f32; 2]; w * h];
    for y in 0..h as i32 {
        let interior_row = y >= 1 && y + 1 < h as i32;
        for x in 0..w as i32 {
            if interior_row && x >= 1 && x + 1 < w as i32 {
                // Same sums as below, read without the edge clamping.
                let i = y as usize * w + x as usize;
                let (n, s) = (i - w, i + w);
                let gx = (p[n + 1] + 2.0 * p[i + 1] + p[s + 1]) - (p[n - 1] + 2.0 * p[i - 1] + p[s - 1]);
                let gy = (p[s - 1] + 2.0 * p[s] + p[s + 1]) - (p[n - 1] + 2.0 * p[n] + p[n + 1]);
                out[i] = [gx * 0.25, gy * 0.25];
                continue;
            }
            let g = |dx: i32, dy: i32| at1(p, w, h, x + dx, y + dy);
            let gx = (g(1, -1) + 2.0 * g(1, 0) + g(1, 1)) - (g(-1, -1) + 2.0 * g(-1, 0) + g(-1, 1));
            let gy = (g(-1, 1) + 2.0 * g(0, 1) + g(1, 1)) - (g(-1, -1) + 2.0 * g(0, -1) + g(1, -1));
            out[y as usize * w + x as usize] = [gx * 0.25, gy * 0.25];
        }
    }
    out
}
