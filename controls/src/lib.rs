//! # Anonymizer Controls
//!
//! A settings holder for the "NZO - Anonymizer" ScriptUI panel: the panel adds this effect to a
//! layer and its expressions read the parameters. Declaring them in a plug-in manifest gives
//! bounded sliders and named menus, which script-made expression controls can't have. The render
//! leaves the pixels untouched (it returns at once). Original NZO effect.

use ecfx::{Frame, Params};

pub const MANIFEST: &str = r#"{
  "api": 1,
  "id": "com.nozomagarion.fx.anonymizer-controls",
  "name": "NZO - Anonymizer Controls",
  "category": "NZO - Tools",
  "version": "1.0.0",
  "author": "Nozomagarion",
  "description": "Settings for the NZO - Anonymizer panel: mask softness and expansion, block size (pixelation layer only). Leaves the pixels unchanged. Original NZO effect.",
  "params": [
    {"id": "contour_px", "name": "Contour (px)", "type": "slider", "default": 20, "min": 0, "max": 500, "sliderMax": 100, "decimals": 0},
    {"id": "expansion_px", "name": "Expansion (px)", "type": "slider", "default": 0, "min": -500, "max": 500, "sliderMin": -100, "sliderMax": 100, "decimals": 0},
    {"id": "taille_des_blocs_px", "name": "Taille des blocs (px)", "type": "slider", "default": 24, "min": 1, "max": 500, "sliderMax": 100, "decimals": 0}
  ]
}"#;

/// Pass-through: the parameters only feed the panel's expressions.
fn render(_f: &mut Frame, _p: &mut Params) -> Result<(), i32> {
    Ok(())
}

ecfx::plugin!(MANIFEST, render);

#[cfg(test)]
mod tests {
    use super::*;

    const NAMES: &[&str] = &["Contour (px)", "Expansion (px)", "Taille des blocs (px)"];

    #[test]
    fn manifest_shape() {
        let d = ecfx::testing::defaults(MANIFEST);
        assert_eq!(d.len(), ecfx::abi::flat_param_count(MANIFEST));
        assert_eq!(d.len(), NAMES.len());
        for name in NAMES {
            assert!(MANIFEST.contains(&format!("\"name\": \"{name}\"")), "missing: {name}");
        }
        for line in MANIFEST.lines().filter(|l| l.contains("\"type\": \"slider\"")) {
            assert!(line.contains("\"min\": ") && line.contains("\"max\": "), "unbounded slider: {line}");
        }
    }

    #[test]
    fn leaves_pixels_unchanged() {
        let d = ecfx::testing::defaults(MANIFEST);
        let (_, _, orig) = ecfx::testing::test_image();
        for t in [0.0, 0.5, 3.0] {
            assert!(ecfx::testing::run(render, &d, t) == orig);
        }
        let extreme: Vec<f64> = d.iter().map(|_| 1e9).collect();
        assert!(ecfx::testing::run(render, &extreme, 1.0) == orig);
    }
}
