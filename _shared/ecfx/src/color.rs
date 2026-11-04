//! Colour helpers. Plug-ins receive premultiplied RGBA; most work happens unpremultiplied.

/// Premultiplied → straight RGBA.
#[inline]
pub fn unpremul(p: [f32; 4]) -> [f32; 4] {
    let a = p[3];
    if a <= 1e-6 {
        [0.0, 0.0, 0.0, 0.0]
    } else {
        let k = 1.0 / a;
        [p[0] * k, p[1] * k, p[2] * k, a]
    }
}

/// Straight → premultiplied RGBA.
#[inline]
pub fn premul(p: [f32; 4]) -> [f32; 4] {
    [p[0] * p[3], p[1] * p[3], p[2] * p[3], p[3]]
}

/// Rec. 709 luminance.
#[inline]
pub fn luma(c: &[f32; 4]) -> f32 {
    0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}

/// RGB (0–1) → HSV with h in [0, 1).
pub fn rgb_to_hsv(r: f32, g: f32, b: f32) -> [f32; 3] {
    let max = r.max(g).max(b);
    let min = r.min(g).min(b);
    let d = max - min;
    let s = if max > 1e-6 { d / max } else { 0.0 };
    let h = if d <= 1e-6 {
        0.0
    } else if max == r {
        ((g - b) / d).rem_euclid(6.0) / 6.0
    } else if max == g {
        ((b - r) / d + 2.0) / 6.0
    } else {
        ((r - g) / d + 4.0) / 6.0
    };
    [h, s, max]
}

/// HSV (h in turns) → RGB.
pub fn hsv_to_rgb(h: f32, s: f32, v: f32) -> [f32; 3] {
    let h = (h - h.floor()) * 6.0;
    let i = h.floor();
    let f = h - i;
    let p = v * (1.0 - s);
    let q = v * (1.0 - s * f);
    let t = v * (1.0 - s * (1.0 - f));
    match i as i32 {
        0 => [v, t, p],
        1 => [q, v, p],
        2 => [p, v, t],
        3 => [p, q, v],
        4 => [t, p, v],
        _ => [v, p, q],
    }
}

/// RGB (0–1) → full-range YCbCr (0–1, chroma centred on 0.5), JPEG / JFIF style.
#[inline]
pub fn rgb_to_ycc(r: f32, g: f32, b: f32) -> [f32; 3] {
    [
        0.299 * r + 0.587 * g + 0.114 * b,
        0.5 - 0.168_736 * r - 0.331_264 * g + 0.5 * b,
        0.5 + 0.5 * r - 0.418_688 * g - 0.081_312 * b,
    ]
}

#[inline]
pub fn ycc_to_rgb(y: f32, cb: f32, cr: f32) -> [f32; 3] {
    let (cb, cr) = (cb - 0.5, cr - 0.5);
    [y + 1.402 * cr, y - 0.344_136 * cb - 0.714_136 * cr, y + 1.772 * cb]
}

/// A colour ramp: `stops` are (position 0–1, rgb), sorted by position.
pub fn ramp(stops: &[(f32, [f32; 3])], t: f32) -> [f32; 3] {
    let Some(first) = stops.first() else { return [t, t, t] };
    if t <= first.0 {
        return first.1;
    }
    for w in stops.windows(2) {
        let (a, b) = (w[0], w[1]);
        if t <= b.0 {
            let k = if b.0 > a.0 { (t - a.0) / (b.0 - a.0) } else { 0.0 };
            return [a.1[0] + (b.1[0] - a.1[0]) * k, a.1[1] + (b.1[1] - a.1[1]) * k, a.1[2] + (b.1[2] - a.1[2]) * k];
        }
    }
    stops[stops.len() - 1].1
}

/// A 256-entry lookup table of a ramp.
pub fn ramp_lut(stops: &[(f32, [f32; 3])]) -> Vec<[f32; 3]> {
    (0..256).map(|i| ramp(stops, i as f32 / 255.0)).collect()
}

/// Looks a 0–1 value up in a 256-entry table.
#[inline]
pub fn lut(table: &[[f32; 3]], t: f32) -> [f32; 3] {
    let i = (t.clamp(0.0, 1.0) * 255.0 + 0.5) as usize;
    table[i.min(table.len().saturating_sub(1))]
}
