# 🖼️ AstrBot Plugin: ImgBB_Subscriber (ImgBB助手)

这是一个用于AstrBot的插件，允许用户抓取指定 ImgBB 用户的公开相册图片，支持对订阅用户随机抓取,使用api_key上传图片到免费图床,以及通过 Cookie 访问受限内容。

## ✨ 功能特性

* **上传图片**：在ImgBB创建用户并获取API_key,即可通过机器人上传图片到ImgBB中。
* **指定抓取**：输入 ImgBB 用户名，随机抓取其相册内的图片。
* **订阅系统**：订阅喜欢的XXX，建立自己的关注列表。
* **随机看图**：从你的订阅列表中随机抽取一位用户并抓取图片。
* **高度自定义**：
    * 自定义每次抓取的**图片数量**。
    * 自定义**返还格式**（仅看图 / 仅看链接 / 图+链）。
* **隐私与网络支持**：
    * 支持 **HTTP 代理**（解决国内无法访问 ImgBB 的问题）。
    * 支持 **Cookie**（解决部分相册需要登录才能查看的问题）。

eg：

<img src="https://i.ibb.co/gbsd6yLC/5f267d418722.jpg" width="300" height="300">

https://i.ibb.co/G35HX7ym/a8ce2764f5f6.jpg
<img src="https://i.ibb.co/G35HX7ym/a8ce2764f5f6.jpg" width="300" height="200">

<img src="https://i.ibb.co/zWktfW9J/b79978ba6fb6.jpg" width="" height="">


## 📦 安装与依赖

1. 将插件文件夹 `imgbb_subscriber` 放入 AstrBot 的 `data/plugins/` 目录中。
2. 安装必要的 Python 依赖库（用于解析网页）：

```bash
pip install beautifulsoup4 aiohttp
```

# imgbb_subscriber 配置指南

本插件使用 AstrBot 标准的 `_conf_schema.json` 配置系统。

## 配置方法

### 方法 1：使用 Web 管理面板（推荐）

1. 启动 AstrBot，访问 Web 管理界面  
2. 进入「插件配置」 → 找到 **imgbb_subscriber**  
3. 直接在界面上填写参数并保存

### 方法 2：手动修改文件

如果未使用 Web 面板，请编辑以下文件：
```bash
data/config/plugin_config/imgbb_subscriber_config.json
```


（文件名可能因 AstrBot 版本略有不同）

## 配置项说明

| 配置项 Key     | 类型   | 默认值 | 说明                                                                 |
|----------------|--------|--------|----------------------------------------------------------------------|
| fetch_count    | int    | 1      | 每次指令抓取的图片数量（建议 1–5）                                    |
| return_type    | int    | 3      | 返回类型：<br>1: 仅发送图片<br>2: 仅发送链接<br>3: 图片 + 链接（推荐） |
| http_proxy     | string | ""     | 代理地址，例如 `http://127.0.0.1:7890`<br>国内网络环境通常必须配置     |
| cookies        | string | ""     | ImgBB 的网页 Cookie<br>用于抓取隐私相册或避免 403 错误                |
| api_key        | string | ""     | （预留字段）暂时不影响抓取功能                                        |

## 🔎 如何获取 Cookie？

1. 用浏览器登录 ImgBB 账号  
2. 按 **F12** 打开开发者工具 → 切换到「网络（Network）」面板  
3. 刷新页面，随意点击一个请求  
4. 在「请求头（Request Headers）」中找到 `Cookie:` 一行，复制完整内容

## 指令列表

| 指令         | 参数     | 说明                              | 示例                   |
|--------------|----------|-----------------------------------|------------------------|
| /imgbb_get   | <用户名> | 随机抓取指定用户的图片            | /imgbb_get wscxr       |
| /imgbb_sub   | <用户名> | 订阅指定用户到你的列表            | /imgbb_sub wscxr       |
| /imgbb_unsub | <用户名> | 取消订阅                          | /imgbb_unsub wscxr     |
| /imgbb_rand  | 无       | 从订阅列表随机挑选一位用户并抓图  | /imgbb_rand            |
| /imgbb_list  | 无       | 查看当前订阅列表                  | /imgbb_list            |
| /upload| `[图片]` | 发送图片时配文使用，将图片上传到 ImgBB 并返回直链。 | `[图片] /upload` |

## ❓ 常见问题 (FAQ)

**Q: 发送指令后提示“HTTP 访问失败”或“超时”？**  
A: ImgBB 在国内通常无法直连。请务必在配置中填写正确的 `http_proxy`（例如 `http://127.0.0.1:7890`）。

**Q: 提示“未找到图片”或“权限不足”？**  
A:

1. 确认该用户主页 `https://用户名.imgbb.com/` 是否真实存在且有公开图片  
2. 如果用户设置了隐私权限（相册非公开），必须填写 `cookies` 配置项来模拟已登录状态

**Q: return_type 填什么好？**  
A: 推荐填 **3**（图片 + 链接）。  
原因：ImgBB 部分直链可能因防盗链机制导致解析失败，此时如果同时发送链接（Type 2 或 3），用户还能手动点击查看；若只选 Type 1（仅图片），链路失败就完全看不到了。

