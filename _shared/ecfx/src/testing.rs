//! Native test helpers (used by each plug-in's `cargo test`): manifest defaults, a synthetic
//! test image and a render call that goes through the same parameter path as the host.

use crate::abi::{Frame, Params, RenderFn};

/// The flattened default values of a manifest, in declaration order.
/// Expects one parameter object per line with `"type": "<kind>"` and `"default": <value>`.
pub fn defaults(manifest: &str) -> Vec<f64> {
    let mut out = Vec::new();
    for line in manifest.lines() {
        let Some(t) = line.find("\"type\": \"") else { continue };
        let kind = &line[t + 9..];
        let kind = &kind[..kind.find('"').unwrap_or(0)];
        let Some(d) = line.find("\"default\": ") else {
            panic!("parameter without default: {line}");
        };
        let v = line[d + 11..].trim_start();
        if let Some(rest) = v.strip_prefix('[') {
            let inner = &rest[..rest.find(']').unwrap_or(0)];
            out.extend(inner.split(',').map(|s| s.trim().parse::<f64>().unwrap_or(0.0)));
        } else {
            let end = v.find([',', '}']).unwrap_or(v.len());
            let tok = v[..end].trim();
            out.push(match tok {
                "true" => 1.0,
                "false" => 0.0,
                n => n.parse::<f64>().unwrap_or(0.0),
            });
        }
        // Points are given as fractions of the layer: the host converts them to buffer pixels.
        if kind == "point" {
            let n = out.len();
            out[n - 2] *= 256.0;
            out[n - 1] *= 144.0;
        }
    }
    out
}

/// A 256×144 premultiplied test image: gradients, a disc, stripes, a transparent corner.
pub fn test_image() -> (usize, usize, Vec<[f32; 4]>) {
    let (w, h) = (256usize, 144usize);
    let mut px = vec![[0.0f32; 4]; w * h];
    for y in 0..h {
        for x in 0..w {
            let u = x as f32 / w as f32;
            let v = y as f32 / h as f32;
            let mut c = [u, v, 1.0 - u * 0.5, 1.0];
            let dx = x as f32 - 150.0;
            let dy = y as f32 - 70.0;
            if dx * dx + dy * dy < 40.0 * 40.0 {
                c = [0.95, 0.72, 0.6, 1.0];
            }
            if (x / 8) % 2 == 0 && y > 110 {
                c = [0.1, 0.1, 0.1, 1.0];
            }
            if x < 20 && y < 20 {
                c[3] = 0.0;
            }
            px[y * w + x] = [c[0] * c[3], c[1] * c[3], c[2] * c[3], c[3]];
        }
    }
    (w, h, px)
}

/// Renders the test image with `params` at `time`.
pub fn run(f: RenderFn, params: &[f64], time: f64) -> Vec<[f32; 4]> {
    let (w, h, mut px) = test_image();
    let mut frame = Frame { w, h, px: &mut px, time, scale: 1.0 };
    let mut p = Params::new(params);
    assert_eq!(f(&mut frame, &mut p), Ok(()));
    for c in px.iter() {
        assert!(c.iter().all(|v| v.is_finite()), "non-finite output");
    }
    px
}

/// The usual checks: the manifest's flattened size, defaults render, determinism, and that
/// the effect changes the image.
pub fn smoke(manifest: &str, f: RenderFn) {
    let d = defaults(manifest);
    assert_eq!(d.len(), crate::abi::flat_param_count(manifest));
    let a = run(f, &d, 0.5);
    let b = run(f, &d, 0.5);
    assert!(a == b, "render is not deterministic");
    let (_, _, orig) = test_image();
    assert!(a != orig, "defaults leave the image unchanged");
}
