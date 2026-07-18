//! 工具函数（对应 Python utils.py）

use serde_json::json;
use std::collections::HashMap;
use std::process::Command;
use tracing::debug;
use uuid::Uuid;

/// 验证 URL 是否有效（支持带认证信息的代理地址）
pub fn is_valid_url(url: &str) -> bool {
    let url = url.trim();
    if url.is_empty() {
        return false;
    }
    // 与 Python 版正则语义对齐的简化校验
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return false;
    }
    url::Url::parse(url).is_ok()
}

/// 查找静态资源 / 模板根目录（相对 Python 项目根）
pub fn find_project_root() -> std::path::PathBuf {
    let candidates = [
        std::path::PathBuf::from("."),
        std::path::PathBuf::from("../.."),
        std::path::PathBuf::from("../../.."),
    ];
    for p in &candidates {
        if p.join("templates").exists() || p.join("config.yml").exists() {
            return p.clone();
        }
    }
    std::path::PathBuf::from("../..")
}

/// 检查 IPv6 地址是否为公网 IP
pub fn is_public_ipv6(ipv6: &str) -> bool {
    let lower = ipv6.to_ascii_lowercase();
    !(lower.starts_with("fe80") || lower.starts_with("fc00") || lower.starts_with("fd00"))
}

/// 执行系统命令并自动多编码尝试解码
pub fn run_cmd_capture(cmd: &[&str]) -> String {
    if cmd.is_empty() {
        return String::new();
    }
    let output = match Command::new(cmd[0]).args(&cmd[1..]).output() {
        Ok(o) => o,
        Err(_) => return String::new(),
    };
    if output.stdout.is_empty() {
        return String::new();
    }
    let candidates = ["utf-8", "gbk", "cp936", "latin-1"];
    for enc in candidates {
        if let Ok(s) = decode_bytes(&output.stdout, enc) {
            return s;
        }
    }
    String::from_utf8_lossy(&output.stdout).into_owned()
}

fn decode_bytes(bytes: &[u8], enc: &str) -> Result<String, ()> {
    match enc {
        "utf-8" => String::from_utf8(bytes.to_vec()).map_err(|_| ()),
        "gbk" | "cp936" => {
            // 简易 GBK：先尝试 UTF-8，失败则 lossy
            String::from_utf8(bytes.to_vec()).or_else(|_| {
                // 使用 encoding_rs 若可用；否则 lossy
                Ok::<String, ()>(String::from_utf8_lossy(bytes).into_owned())
            })
        }
        "latin-1" => Ok(bytes.iter().map(|&b| b as char).collect()),
        _ => Err(()),
    }
}

/// 检查系统中是否存在永久有效的 IPv6 地址
/// 返回 (has_permanent, sample_address)
pub fn check_has_permanent_ipv6() -> (bool, Option<String>) {
    #[cfg(windows)]
    {
        let output = run_cmd_capture(&["netsh", "interface", "ipv6", "show", "addresses"]);
        for line in output.lines() {
            let line_strip = line.trim();
            if (line_strip.contains("手动") || line_strip.contains("Manual"))
                && line_strip.contains(':')
            {
                let parts: Vec<&str> = line_strip.split_whitespace().collect();
                if let Some(last) = parts.last() {
                    let candidate = last.split('/').next().unwrap_or("");
                    if candidate.contains(':') && is_public_ipv6(candidate) {
                        return (true, Some(candidate.to_string()));
                    }
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let output = run_cmd_capture(&["ip", "-6", "addr", "show"]);
        let lines: Vec<&str> = output.lines().collect();
        for i in 0..lines.len() {
            let line_strip = lines[i].trim();
            if line_strip.contains("inet6") && line_strip.contains("scope global") {
                if let Some(candidate) = line_strip.split_whitespace().nth(1) {
                    let candidate = candidate.split('/').next().unwrap_or("");
                    if is_public_ipv6(candidate) {
                        if i + 1 < lines.len() {
                            let next_line = lines[i + 1].trim();
                            if next_line.contains("valid_lft forever") {
                                return (true, Some(candidate.to_string()));
                            }
                        }
                    }
                }
            }
        }
    }
    (false, None)
}

/// 获取系统网卡列表
pub fn get_network_interfaces() -> Vec<serde_json::Value> {
    let mut interfaces = Vec::new();
    #[cfg(windows)]
    {
        let output = run_cmd_capture(&["netsh", "interface", "show", "interface"]);
        for line in output.lines().skip(3) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                let interface_name = parts[3..].join(" ");
                if !interface_name.is_empty()
                    && interface_name != "Loopback"
                    && interface_name != "环回"
                {
                    interfaces.push(json!({
                        "name": interface_name,
                        "display": interface_name,
                    }));
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let output = run_cmd_capture(&["ip", "link", "show"]);
        for line in output.lines() {
            if line.contains(':') && !line.starts_with(' ') {
                let parts: Vec<&str> = line.split(':').collect();
                if parts.len() >= 2 {
                    let interface_name = parts[1].trim();
                    if !interface_name.is_empty() && interface_name != "lo" {
                        interfaces.push(json!({
                            "name": interface_name,
                            "display": interface_name,
                        }));
                    }
                }
            }
        }
    }
    interfaces
}

/// 获取本地公网 IPv6 地址
pub fn get_local_ipv6_addresses() -> Vec<String> {
    let mut addresses = Vec::new();
    #[cfg(windows)]
    {
        let output = run_cmd_capture(&["netsh", "interface", "ipv6", "show", "addresses"]);
        for line in output.lines() {
            let line_strip = line.trim();
            if (line_strip.contains("公用")
                || line_strip.contains("手动")
                || line_strip.contains("Public")
                || line_strip.contains("Manual"))
                && line_strip.contains(':')
            {
                let parts: Vec<&str> = line_strip.split_whitespace().collect();
                if let Some(last) = parts.last() {
                    let candidate = last.split('/').next().unwrap_or("");
                    if candidate.contains(':') && is_public_ipv6(candidate) {
                        addresses.push(candidate.to_string());
                    }
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let output = run_cmd_capture(&["ip", "-6", "addr", "show"]);
        for line in output.lines() {
            let line_strip = line.trim();
            if line_strip.contains("inet6") && line_strip.contains("scope global") {
                if let Some(candidate) = line_strip.split_whitespace().nth(1) {
                    let candidate = candidate.split('/').next().unwrap_or("");
                    if is_public_ipv6(candidate) {
                        addresses.push(candidate.to_string());
                    }
                }
            }
        }
    }
    // 去重保序
    let mut seen = HashMap::new();
    addresses
        .into_iter()
        .filter(|a| seen.insert(a.clone(), ()).is_none())
        .collect()
}

/// 配置指定数量的 IPv6 地址到网卡
pub fn configure_ipv6_addresses(prefix: &str, count: usize, adapter_name: &str) {
    for _ in 0..count {
        let guid = Uuid::new_v4().simple().to_string();
        let new_temp_ipv6 = format!(
            "{}:{}:{}:{}:{}",
            prefix,
            &guid[0..4],
            &guid[4..8],
            &guid[8..12],
            &guid[12..16]
        );
        #[cfg(windows)]
        {
            let status = Command::new("netsh")
                .args([
                    "interface",
                    "ipv6",
                    "add",
                    "address",
                    adapter_name,
                    &new_temp_ipv6,
                    "store=active",
                    "skipassource=true",
                ])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
            if let Err(e) = status {
                debug!("配置 IPv6 地址失败: {e}");
            }
        }
        #[cfg(not(windows))]
        {
            let status = Command::new("ip")
                .args(["-6", "addr", "add", &new_temp_ipv6, "dev", adapter_name])
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();
            if let Err(e) = status {
                debug!("配置 IPv6 地址失败: {e}");
            }
        }
    }
}
