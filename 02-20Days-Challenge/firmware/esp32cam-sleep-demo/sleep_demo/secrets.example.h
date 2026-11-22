#pragma once
// 复制为 secrets.h 后填入自己的 Wi-Fi / 静态 IP；secrets.h 已被 .gitignore 忽略，不要提交。
static const char *kWifiSsid = "YOUR_SSID";
static const char *kWifiPass = "YOUR_PASSWORD";

// 静态 IP 必须与路由器 / 热点同网段；下面只是示例，按实际网段改。
static const IPAddress kStaticIp(192, 168, 1, 50);
static const IPAddress kGateway(192, 168, 1, 1);
static const IPAddress kSubnet(255, 255, 255, 0);
static const IPAddress kDns1(192, 168, 1, 1);
static const IPAddress kDns2(223, 5, 5, 5);
