/// 枚举全部非回环 IPv4 地址；热点网卡常不是默认路由网卡
#[must_use]
pub fn lan_ips() -> Vec<String> {
    if_addrs::get_if_addrs()
        .map(|list| {
            list.into_iter()
                .filter(|i| !i.is_loopback())
                .filter_map(|i| match i.addr {
                    if_addrs::IfAddr::V4(v4) => Some(v4.ip.to_string()),
                    if_addrs::IfAddr::V6(_) => None,
                })
                .collect()
        })
        .unwrap_or_default()
}
