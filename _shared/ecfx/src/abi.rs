//! ABI v1 glue: the host buffer, the frame and the flattened parameters.

use std::cell::RefCell;

thread_local! {
    /// One reusable, 8-byte-aligned buffer for the parameters followed by the pixels.
    static BUF: RefCell<Vec<u64>> = const { RefCell::new(Vec::new()) };
}

/// `ec_alloc`: a buffer of at least `bytes` bytes, 8-byte aligned (reused between frames).
pub fn alloc(bytes: i32) -> i32 {
    BUF.with(|b| {
        let mut b = b.borrow_mut();
        let words = (bytes.max(0) as usize).div_ceil(8);
        if b.len() < words {
            b.resize(words, 0);
        }
        b.as_mut_ptr() as usize as i32
    })
}

/// The frame handed to a render function.
pub struct Frame<'a> {
    pub w: usize,
    pub h: usize,
    /// Premultiplied RGBA, row-major, `w * h` pixels.
    pub px: &'a mut [[f32; 4]],
    /// Layer time in seconds.
    pub time: f64,
    /// Buffer pixels per layer pixel (< 1 at reduced preview resolution). Multiply every size
    /// parameter expressed in pixels by it so previews match full-resolution renders.
    pub scale: f32,
}

impl Frame<'_> {
    #[inline]
    pub fn len(&self) -> usize {
        self.w * self.h
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.w == 0 || self.h == 0
    }

    /// A size in layer pixels converted to buffer pixels (at least `min`).
    #[inline]
    pub fn px_size(&self, layer_px: f32, min: f32) -> f32 {
        (layer_px * self.scale).max(min)
    }

    /// A frame counter derived from time, for per-frame randomness (assumes ≤ 1000 fps).
    #[inline]
    pub fn time_key(&self) -> u32 {
        (self.time * 1000.0).round() as i64 as u32
    }
}

/// Sequential reader of the flattened parameters, in manifest declaration order.
/// Missing values read as 0 so a mismatch can never trap.
pub struct Params<'a> {
    v: &'a [f64],
    i: usize,
}

impl<'a> Params<'a> {
    pub fn new(v: &'a [f64]) -> Self {
        Params { v, i: 0 }
    }

    /// How many flattened values were passed.
    pub fn count(&self) -> usize {
        self.v.len()
    }

    #[inline]
    fn next(&mut self) -> f64 {
        let x = self.v.get(self.i).copied().unwrap_or(0.0);
        self.i += 1;
        if x.is_finite() { x } else { 0.0 }
    }

    /// A slider as is.
    pub fn f(&mut self) -> f32 {
        self.next() as f32
    }

    /// A slider given in percent, as 0–1 (not clamped).
    pub fn pct(&mut self) -> f32 {
        (self.next() / 100.0) as f32
    }

    /// An angle parameter (degrees) as radians.
    pub fn angle(&mut self) -> f32 {
        self.next().to_radians() as f32
    }

    /// A checkbox.
    pub fn b(&mut self) -> bool {
        self.next() != 0.0
    }

    /// A popup (0-based index) or an integer slider.
    pub fn i(&mut self) -> i32 {
        self.next().round() as i32
    }

    /// A point, already in buffer pixels.
    pub fn point(&mut self) -> [f32; 2] {
        [self.next() as f32, self.next() as f32]
    }

    /// A colour, RGBA 0–1.
    pub fn color(&mut self) -> [f32; 4] {
        [self.next() as f32, self.next() as f32, self.next() as f32, self.next() as f32]
    }
}

/// Signature of a plug-in's render function. `Err(code)` leaves the frame unchanged.
pub type RenderFn = fn(&mut Frame, &mut Params) -> Result<(), i32>;

/// `ec_render`: wraps the raw pointers and calls `f`.
///
/// # Safety
/// `pixels` and `params` must point into the buffer returned by [`alloc`], holding
/// `width * height` RGBA `f32` pixels and `nparams` `f64`s.
#[allow(clippy::too_many_arguments)]
pub unsafe fn render(pixels: i32, width: i32, height: i32, params: i32, nparams: i32, time: f64, scale: f64, f: RenderFn) -> i32 {
    if width <= 0 || height <= 0 {
        return 0;
    }
    let (w, h) = (width as usize, height as usize);
    let n = nparams.max(0) as usize;
    let p = if n == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(params as u32 as usize as *const f64, n) } };
    let px = unsafe { std::slice::from_raw_parts_mut(pixels as u32 as usize as *mut [f32; 4], w * h) };
    let scale = if scale.is_finite() && scale > 0.0 { scale as f32 } else { 1.0 };
    let mut frame = Frame { w, h, px, time: if time.is_finite() { time } else { 0.0 }, scale };
    let mut params = Params::new(p);
    match f(&mut frame, &mut params) {
        Ok(()) => 0,
        Err(code) => code.max(1),
    }
}

/// Number of flattened `f64` values a manifest's parameters produce (for tests).
/// Expects the manifest's own formatting: `"type": "<kind>"`.
pub fn flat_param_count(manifest: &str) -> usize {
    let mut n = 0;
    let mut rest = manifest;
    while let Some(i) = rest.find("\"type\": \"") {
        rest = &rest[i + 9..];
        let end = rest.find('"').unwrap_or(0);
        n += match &rest[..end] {
            "point" => 2,
            "color" => 4,
            _ => 1,
        };
    }
    n
}
