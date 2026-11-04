//! # ecfx — shared code of the EffectCraft WebAssembly plug-ins
//!
//! EffectCraft (official build, v0.8+) loads effect plug-ins as WebAssembly modules that follow
//! **plug-in API 1 / WASM ABI 1** (see `HANDOFF.md` at the repository root):
//!
//! | export | signature |
//! |---|---|
//! | `memory` | linear memory |
//! | `ec_api_version` | `() -> i32` (returns 1) |
//! | `ec_manifest_ptr`, `ec_manifest_len` | `() -> i32` (UTF-8 JSON manifest) |
//! | `ec_alloc` | `(bytes: i32) -> i32` (8-byte aligned buffer) |
//! | `ec_render` | `(pixels, width, height, params, nparams: i32, time: f64, scale: f64) -> i32` |
//!
//! Pixels are premultiplied RGBA `f32`, row-major, processed in place. Parameters arrive as
//! `f64`s in declaration order (slider/angle/checkbox/popup: 1 value, point: 2 in buffer pixels,
//! colour: 4). Rendering must be deterministic and must not import anything.
//!
//! Every plug-in crate calls [`plugin!`] with its manifest and its render function.

pub mod abi;
pub mod color;
pub mod draw;
pub mod font;
pub mod img;
pub mod math;
pub mod testing;

pub use abi::{Frame, Params};

/// Declares the five ABI exports of a plug-in.
///
/// ```ignore
/// const MANIFEST: &str = r#"{ "api": 1, ... }"#;
/// fn render(f: &mut ecfx::Frame, p: &mut ecfx::Params) -> Result<(), i32> { Ok(()) }
/// ecfx::plugin!(MANIFEST, render);
/// ```
#[macro_export]
macro_rules! plugin {
    ($manifest:expr, $render:path) => {
        #[unsafe(no_mangle)]
        pub extern "C" fn ec_api_version() -> i32 {
            1
        }

        #[unsafe(no_mangle)]
        pub extern "C" fn ec_manifest_ptr() -> i32 {
            $manifest.as_ptr() as usize as i32
        }

        #[unsafe(no_mangle)]
        pub extern "C" fn ec_manifest_len() -> i32 {
            $manifest.len() as i32
        }

        #[unsafe(no_mangle)]
        pub extern "C" fn ec_alloc(bytes: i32) -> i32 {
            $crate::abi::alloc(bytes)
        }

        /// # Safety
        /// The host passes pointers into the buffer `ec_alloc` returned.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn ec_render(pixels: i32, width: i32, height: i32, params: i32, nparams: i32, time: f64, scale: f64) -> i32 {
            unsafe { $crate::abi::render(pixels, width, height, params, nparams, time, scale, $render) }
        }
    };
}
