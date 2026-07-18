//! 滑块验证码缺口定位（高速版）
//!
//! 优化点：
//! - 小图只读 PNG IHDR，不完整解码
//! - zune-png 快速解码大图
//! - 下采样 + 量化单次遍历
//! - 复用缓冲区，只检查 Top-3 高频色
//! - 跳过左 1/4 区域，找到足够大缺口可提前结束

use base64::{engine::general_purpose::STANDARD, Engine};
use tracing::info;
use zune_core::colorspace::ColorSpace;
use zune_core::options::DecoderOptions;
use zune_png::PngDecoder;

/// 仅从 PNG IHDR 读取宽高（24 字节内完成）
fn png_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    if bytes.len() < 24 || &bytes[0..8] != b"\x89PNG\r\n\x1a\n" {
        return None;
    }
    if &bytes[12..16] != b"IHDR" {
        return None;
    }
    let w = u32::from_be_bytes(bytes[16..20].try_into().ok()?);
    let h = u32::from_be_bytes(bytes[20..24].try_into().ok()?);
    if w == 0 || h == 0 {
        return None;
    }
    Some((w, h))
}

/// 解码 PNG → RGB8 原始缓冲
fn decode_png_rgb(bytes: &[u8]) -> Result<(u32, u32, Vec<u8>), String> {
    let opts = DecoderOptions::default().png_set_strip_to_8bit(true);
    let mut decoder = PngDecoder::new_with_options(bytes, opts);
    decoder
        .decode_headers()
        .map_err(|e| format!("PNG 头解析失败: {e}"))?;
    let info = decoder
        .get_info()
        .ok_or_else(|| "PNG 缺少信息头".to_string())?;
    let w = info.width as u32;
    let h = info.height as u32;
    let decoded = decoder
        .decode()
        .map_err(|e| format!("PNG 解码失败: {e}"))?;
    let rgb = match decoded {
        zune_core::result::DecodingResult::U8(v) => {
            let cs = decoder.get_colorspace().unwrap_or(ColorSpace::RGB);
            match cs {
                ColorSpace::RGB => v,
                ColorSpace::RGBA => {
                    let mut out = Vec::with_capacity((v.len() / 4) * 3);
                    for px in v.chunks_exact(4) {
                        out.extend_from_slice(&px[..3]);
                    }
                    out
                }
                ColorSpace::Luma => {
                    let mut out = Vec::with_capacity(v.len() * 3);
                    for &g in &v {
                        out.extend_from_slice(&[g, g, g]);
                    }
                    out
                }
                ColorSpace::LumaA => {
                    let mut out = Vec::with_capacity((v.len() / 2) * 3);
                    for px in v.chunks_exact(2) {
                        out.extend_from_slice(&[px[0], px[0], px[0]]);
                    }
                    out
                }
                other => {
                    return Err(format!("不支持的 PNG 色彩空间: {other:?}"));
                }
            }
        }
        _ => return Err("PNG 位深不支持".into()),
    };
    if rgb.len() < (w as usize) * (h as usize) * 3 {
        return Err("PNG 像素数据长度不足".into());
    }
    Ok((w, h, rgb))
}

/// 在大图上找纯色近正方形缺口，返回 x 偏移量
pub fn match_slider_offset(small_image_b64: &str, big_image_b64: &str) -> Result<i32, String> {
    let small_bytes = STANDARD
        .decode(small_image_b64.trim())
        .map_err(|e| format!("小图 base64 失败: {e}"))?;
    let big_bytes = STANDARD
        .decode(big_image_b64.trim())
        .map_err(|e| format!("大图 base64 失败: {e}"))?;

    let (sw, sh) = png_dimensions(&small_bytes).ok_or_else(|| "小图尺寸无效".to_string())?;
    let (bw, bh, rgb) = decode_png_rgb(&big_bytes)?;

    let w = (bw / 2) as usize;
    let h = (bh / 2) as usize;
    if w == 0 || h == 0 {
        return Err("大图尺寸无效".into());
    }

    let min_side = ((sw.min(sh) as f32) * 0.25) as i32;
    let min_side = min_side.max(1);
    let skip_left = (sw / 4) as usize;
    // 预期缺口面积量级，达到后可提前结束
    let good_enough = (min_side * min_side * 3) / 2;

    // 单次下采样 + 量化 → color_id
    let mut color_id = vec![0u32; w * h];
    let stride = (bw as usize) * 3;
    for y in 0..h {
        let src_row = (y * 2) * stride;
        let dst_row = y * w;
        for x in 0..w {
            let i = src_row + (x * 2) * 3;
            let q0 = (rgb[i] >> 2) << 2;
            let q1 = (rgb[i + 1] >> 2) << 2;
            let q2 = (rgb[i + 2] >> 2) << 2;
            color_id[dst_row + x] =
                q0 as u32 | ((q1 as u32) << 8) | ((q2 as u32) << 16);
        }
    }

    // 直方图
    let mut counts: std::collections::HashMap<u32, u32> =
        std::collections::HashMap::with_capacity(128);
    for &c in &color_id {
        *counts.entry(c).or_default() += 1;
    }
    let mut ranked: Vec<(u32, u32)> = counts.into_iter().collect();
    let top_n = 3.min(ranked.len());
    if top_n == 0 {
        return Err("未找到缺口".into());
    }
    ranked.select_nth_unstable_by(top_n - 1, |a, b| b.1.cmp(&a.1));
    let top: Vec<u32> = ranked[..top_n].iter().map(|(c, _)| *c).collect();

    let mut best_area = 0i32;
    let mut best_x = 0i32;
    let mut mask = vec![0u8; w * h];
    let mut col_run = vec![0i32; w * h];

    for &c in &top {
        for i in 0..(w * h) {
            mask[i] = (color_id[i] == c) as u8;
        }

        for x in 0..w {
            col_run[x] = mask[x] as i32;
        }
        for y in 1..h {
            let row = y * w;
            let prev = (y - 1) * w;
            for x in 0..w {
                col_run[row + x] = if mask[row + x] != 0 {
                    col_run[prev + x] + 1
                } else {
                    0
                };
            }
        }

        for y in (min_side as usize)..h {
            let row_base = y * w;
            let mut x = skip_left;
            while x < w {
                if col_run[row_base + x] < min_side {
                    x += 1;
                    continue;
                }
                let s = x;
                while x < w && col_run[row_base + x] >= min_side {
                    x += 1;
                }
                let run_w = (x - s) as i32;
                let run_h = col_run[row_base + s];
                if run_h > 0 {
                    let ratio = run_w as f32 / run_h as f32;
                    let area = run_w * run_h;
                    if (0.7..1.4).contains(&ratio) && area > best_area {
                        best_area = area;
                        best_x = s as i32;
                        if best_area >= good_enough {
                            let offset_x = best_x * 2;
                            info!("缺口定位：x={offset_x}, 滑块={sw}x{sh}");
                            return Ok(offset_x);
                        }
                    }
                }
            }
        }
    }

    if best_area == 0 {
        return Err("未找到缺口".into());
    }

    let offset_x = best_x * 2;
    info!("缺口定位：x={offset_x}, 滑块={sw}x{sh}");
    Ok(offset_x)
}
