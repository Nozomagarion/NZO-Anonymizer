//! Vector-ish drawing on premultiplied RGBA buffers: lines, rectangles, circles, brackets and
//! glyphs scaled into a cell. Colours are straight RGBA; drawing blends "over".

use crate::font::glyph;

/// Blends a straight RGBA colour over one pixel with extra coverage `cov`.
#[inline]
pub fn blend(px: &mut [[f32; 4]], w: usize, h: usize, x: i32, y: i32, c: [f32; 4], cov: f32) {
    if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 {
        return;
    }
    let a = (c[3] * cov).clamp(0.0, 1.0);
    if a <= 0.0 {
        return;
    }
    let p = &mut px[y as usize * w + x as usize];
    for k in 0..3 {
        p[k] = c[k] * a + p[k] * (1.0 - a);
    }
    p[3] = a + p[3] * (1.0 - a);
}

/// Adds light (straight colour × coverage) to a pixel; alpha grows accordingly.
#[inline]
pub fn add(px: &mut [[f32; 4]], w: usize, h: usize, x: i32, y: i32, c: [f32; 4], cov: f32) {
    if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 {
        return;
    }
    let a = (c[3] * cov).max(0.0);
    let p = &mut px[y as usize * w + x as usize];
    for k in 0..3 {
        p[k] += c[k] * a;
    }
    p[3] = (p[3] + a).min(1.0);
}

/// A thick line (square brush of side `t`).
#[allow(clippy::too_many_arguments)]
pub fn line(px: &mut [[f32; 4]], w: usize, h: usize, x0: f32, y0: f32, x1: f32, y1: f32, t: f32, c: [f32; 4]) {
    let dx = x1 - x0;
    let dy = y1 - y0;
    let len = dx.abs().max(dy.abs()).max(1.0);
    if len > 20_000.0 {
        return;
    }
    let steps = len.ceil() as i32;
    let r = ((t - 1.0) * 0.5).max(0.0);
    let ri = r.ceil() as i32;
    let mut last = (i32::MIN, i32::MIN);
    for s in 0..=steps {
        let f = s as f32 / steps as f32;
        let x = (x0 + dx * f).round() as i32;
        let y = (y0 + dy * f).round() as i32;
        if (x, y) == last {
            continue;
        }
        last = (x, y);
        for oy in -ri..=ri {
            for ox in -ri..=ri {
                blend(px, w, h, x + ox, y + oy, c, 1.0);
            }
        }
    }
}

/// A dashed line: `dash` px on, `gap` px off.
#[allow(clippy::too_many_arguments)]
pub fn dashed(px: &mut [[f32; 4]], w: usize, h: usize, x0: f32, y0: f32, x1: f32, y1: f32, t: f32, dash: f32, gap: f32, c: [f32; 4]) {
    let len = ((x1 - x0).powi(2) + (y1 - y0).powi(2)).sqrt();
    if len < 1.0 {
        return;
    }
    let (ux, uy) = ((x1 - x0) / len, (y1 - y0) / len);
    let mut d = 0.0;
    while d < len {
        let e = (d + dash).min(len);
        line(px, w, h, x0 + ux * d, y0 + uy * d, x0 + ux * e, y0 + uy * e, t, c);
        d += dash + gap;
    }
}

/// Rectangle outline.
#[allow(clippy::too_many_arguments)]
pub fn rect(px: &mut [[f32; 4]], w: usize, h: usize, x0: f32, y0: f32, x1: f32, y1: f32, t: f32, c: [f32; 4]) {
    line(px, w, h, x0, y0, x1, y0, t, c);
    line(px, w, h, x1, y0, x1, y1, t, c);
    line(px, w, h, x1, y1, x0, y1, t, c);
    line(px, w, h, x0, y1, x0, y0, t, c);
}

/// Corner brackets of a rectangle (`arm` px long).
#[allow(clippy::too_many_arguments)]
pub fn brackets(px: &mut [[f32; 4]], w: usize, h: usize, x0: f32, y0: f32, x1: f32, y1: f32, arm: f32, t: f32, c: [f32; 4]) {
    let ax = arm.min((x1 - x0) * 0.5);
    let ay = arm.min((y1 - y0) * 0.5);
    for (cx, cy, sx, sy) in [(x0, y0, 1.0, 1.0), (x1, y0, -1.0, 1.0), (x0, y1, 1.0, -1.0), (x1, y1, -1.0, -1.0)] {
        line(px, w, h, cx, cy, cx + ax * sx, cy, t, c);
        line(px, w, h, cx, cy, cx, cy + ay * sy, t, c);
    }
}

/// Circle outline (or filled when `fill`).
#[allow(clippy::too_many_arguments)]
pub fn circle(px: &mut [[f32; 4]], w: usize, h: usize, cx: f32, cy: f32, r: f32, t: f32, fill: bool, c: [f32; 4]) {
    if r <= 0.0 || r > 20_000.0 {
        return;
    }
    let ro = r + t * 0.5;
    let ri = (r - t * 0.5).max(0.0);
    let x0 = (cx - ro - 1.0).floor() as i32;
    let x1 = (cx + ro + 1.0).ceil() as i32;
    let y0 = (cy - ro - 1.0).floor() as i32;
    let y1 = (cy + ro + 1.0).ceil() as i32;
    for y in y0.max(0)..=y1.min(h as i32 - 1) {
        for x in x0.max(0)..=x1.min(w as i32 - 1) {
            let d = ((x as f32 + 0.5 - cx).powi(2) + (y as f32 + 0.5 - cy).powi(2)).sqrt();
            let cov = if fill { (ro - d + 0.5).clamp(0.0, 1.0) } else { ((ro - d + 0.5).clamp(0.0, 1.0)) * ((d - ri + 0.5).clamp(0.0, 1.0)) };
            if cov > 0.0 {
                blend(px, w, h, x, y, c, cov);
            }
        }
    }
}

/// Draws one glyph stretched into the cell (x, y, cw, ch); `bold` thickens it by one dot.
#[allow(clippy::too_many_arguments)]
pub fn glyph_cell(px: &mut [[f32; 4]], w: usize, h: usize, x: i32, y: i32, cw: i32, ch: i32, ch_: char, c: [f32; 4]) {
    let Some(rows) = glyph(ch_) else { return };
    if cw < 1 || ch < 1 {
        return;
    }
    for yy in 0..ch {
        let gy = (yy * 7 / ch).min(6) as usize;
        let bits = rows[gy];
        for xx in 0..cw {
            let gx = (xx * 5 / cw).min(4);
            if bits & (0x10 >> gx) != 0 {
                blend(px, w, h, x + xx, y + yy, c, 1.0);
            }
        }
    }
}
