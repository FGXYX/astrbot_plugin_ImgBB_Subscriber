import asyncio
import base64
import json
import os
import random
import ssl
import re
from urllib.parse import urljoin, urlparse
from pathlib import Path
import aiofiles
import uuid
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup

from astrbot.api.all import Context, Star, register, AstrMessageEvent, logger
from astrbot.api.event import filter
from astrbot.api.message_components import Image, Plain, File  

@register("ImgBB_Subscriber", "FGXYX", "ImgBB助手", "1.1.0")
class ImgBBPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

        # 插件代码目录（可被更新覆盖）
        self.plugin_dir = Path(__file__).parent

        # 持久化数据目录：相对路径，从 bot 根目录开始（跨平台）
        self.persistent_data_dir = Path("data") / "plugin_data" / "astrbot_plugin_imgbb_subscriber"
        self.persistent_data_dir.mkdir(parents=True, exist_ok=True)

        self.download_dir = self.persistent_data_dir / "downloads"
        self.download_dir.mkdir(exist_ok=True)

        self.data_file = self.persistent_data_dir / "data.json"

        logger.info(f"当前工作目录: {Path.cwd().absolute()}")
        logger.info(f"插件代码目录: {self.plugin_dir.absolute()}")
        logger.info(f"持久化数据目录: {self.persistent_data_dir.absolute()}")
        logger.info(f"订阅数据文件: {self.data_file.absolute()}")

        self.data_lock = asyncio.Lock()
        self.data = {}
        self._load_data_sync()

    def _load_data_sync(self):
        if not self.data_file.exists():
            logger.warning(f"data.json 不存在: {self.data_file.absolute()}，初始化空订阅")
            self._save_data_internal({"subs": {}})
            self.data = {"subs": {}}
        else:
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"加载 data.json 成功！订阅内容: {json.dumps(self.data.get('subs', {}), ensure_ascii=False)}")
            except Exception as e:
                logger.error(f"加载 data.json 失败: {self.data_file.absolute()} - {str(e)}，重置为空")
                self.data = {"subs": {}}
                self._save_data_internal({"subs": {}})

    async def _save_data(self): 
            try:
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                logger.info(f"订阅数据保存成功！文件: {self.data_file.absolute()}，订阅内容: {json.dumps(self.data.get('subs', {}), ensure_ascii=False)}")
            except Exception as e:
                logger.error(f"保存 data.json 失败: {str(e)}")
                # fallback 保存到插件目录
                fallback_file = self.plugin_dir / "data.json"
                try:
                    with open(fallback_file, 'w', encoding='utf-8') as f:
                        json.dump(self.data, f, indent=2, ensure_ascii=False)
                    logger.warning(f"fallback 保存到插件目录: {fallback_file}")
                except Exception as fb_e:
                    logger.error(f"fallback 保存失败: {fb_e}")
    def _save_data_internal(self, data):
        """底层保存逻辑"""
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ==========================
    #  网络请求封装
    # ==========================
    async def _request(self, method: str, url: str, **kwargs):
        proxy = self.config.get("http_proxy")
        timeout = aiohttp.ClientTimeout(total=kwargs.pop('timeout', 15))
        
        ssl_ctx = ssl.create_default_context()
        if not kwargs.pop('verify_ssl', True):
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method, 
                    url, 
                    proxy=proxy, 
                    ssl=ssl_ctx, 
                    **kwargs
                ) as resp:
                    if resp.status != 200:
                        return None, f"HTTP {resp.status}"
                    if kwargs.get('expect_bytes'):
                        return await resp.read(), "success"
                    elif kwargs.get('expect_json'):
                        return await resp.json(), "success"
                    else:
                        return await resp.text(), "success"
        except asyncio.TimeoutError:
            return None, "请求超时"
        except Exception as e:
            logger.error(f"网络请求异常 [{url}]: {e}")
            return None, f"网络错误: {str(e)}"

    # ==========================
    #  功能模块 1: 图片上传
    # ==========================
    @filter.command("upload")
    async def upload_image(self, event: AstrMessageEvent):
        '''上传图片到 ImgBB'''
        api_key = self.config.get("api_key")
        if not api_key:
            yield event.plain_result("❌ 未配置 API Key！")
            return

        target_img = next((c for c in event.message_obj.message if isinstance(c, Image)), None)
        if not target_img:
            yield event.plain_result("❌ 请在发送图片时附带 `/upload` 命令")
            return

        yield event.plain_result("☁️ 正在上传...")

        if target_img.path and os.path.exists(target_img.path):
             with open(target_img.path, "rb") as f:
                 img_bytes = f.read()
        elif target_img.url:
             img_bytes, msg = await self._request("GET", target_img.url, expect_bytes=True)
             if not img_bytes:
                 yield event.plain_result(f"❌ 图片下载失败: {msg}")
                 return
        else:
            yield event.plain_result("❌ 无法获取图片数据")
            return

        b64_data = base64.b64encode(img_bytes).decode('utf-8')
        payload = {"key": api_key, "image": b64_data}
        
        res_data, msg = await self._request(
            "POST", 
            "https://api.imgbb.com/1/upload", 
            data=payload, 
            expect_json=True
        )

        if res_data and res_data.get("success"):
            img_url = res_data["data"]["url"]
            yield event.chain_result([
                Plain("✅ **上传成功！**\n"),
                Plain(f"🔗 直链: {img_url}\n"),
                Plain(f"Markdown: `![]({img_url})`")
            ])
        else:
            err_msg = res_data.get("error", {}).get("message", "未知错误") if res_data else msg
            yield event.plain_result(f"❌ 上传失败: {err_msg}")

    # ==========================
    #  功能模块 2: 订阅与抓取
    # ==========================
    async def _fetch_user_images(self, username):
        count = self.config.get("fetch_count", 1)
        max_pages = self.config.get("max_pages", 5)  # 图片页深度
        max_albums = self.config.get("max_albums", 1)  # 新增: 随机选几个相册 (默认1)
        base_url = f"https://{username}.imgbb.com/albums"  # 先抓相册列表

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if self.config.get("cookie"):
            headers["Cookie"] = self.config.get("cookie").strip()
            logger.info(f"[{username}] Using provided Cookie for request")

        # 先抓相册列表页
        logger.info(f"[{username}] Fetching albums page: {base_url}")
        html, msg = await self._request("GET", base_url, headers=headers)
        if not html:
            logger.error(f"[{username}] Albums request failed: {msg}, fallback to user home")
            base_url = f"https://{username}.imgbb.com/"  # 失败 fallback 到用户首页
            html, msg = await self._request("GET", base_url, headers=headers)
            if not html:
                return None, msg

        # 解析相册链接（类似 _parse_gallery_links，但针对 albums）
        soup = BeautifulSoup(html, 'html.parser')
        album_urls = []
        for a in soup.find_all('a', href=re.compile(r'/album/[a-zA-Z0-9]+')):
            href = a.get('href')
            if href:
                album_urls.append(urljoin(base_url, href))
        album_urls = list(set(album_urls))  # 去重

        logger.info(f"[{username}] Found {len(album_urls)} album URLs")

        if not album_urls:
            # 无相册，fallback 到用户首页抓图片
            logger.warning(f"[{username}] No albums found, grabbing from user home")
            all_viewer_urls = self._parse_gallery_links(html, base_url)
        else:
            # 随机选 max_albums 个相册
            selected_albums = random.sample(album_urls, min(len(album_urls), max_albums))
            logger.info(f"[{username}] Selected {len(selected_albums)} albums: {selected_albums}")
            
            all_viewer_urls = []
            for album_url in selected_albums:
                # 进入相册，抓取里面的图片（复用翻页逻辑）
                current_url = album_url
                page = 1
                while page <= max_pages:
                    logger.info(f"[{username}] Fetching album page {page}: {current_url}")
                    html, msg = await self._request("GET", current_url, headers=headers)
                    if not html:
                        break

                    new_urls = self._parse_gallery_links(html, current_url)
                    logger.debug(f"[{username}] Album page {page}: found {len(new_urls)} viewer URLs")
                    if new_urls:
                        all_viewer_urls.extend(new_urls)
                    else:
                        break

                    # 翻页逻辑（原有）
                    soup = BeautifulSoup(html, 'html.parser')
                    next_link = None
                    # ... (你的加强版 next_link 查找代码，保持原样)
                    if not next_link or 'href' not in next_link.attrs:
                        logger.info(f"[{username}] No next in album on page {page}")
                        break

                    next_href = next_link['href']
                    current_url = urljoin(current_url, next_href)
                    page += 1
                    await asyncio.sleep(random.uniform(1.5, 4.0))

        if not all_viewer_urls:
            return None, "未找到图片 (可能是无相册或私有)"

        all_viewer_urls = list(set(all_viewer_urls))
        logger.info(f"[{username}] Total unique viewer URLs: {len(all_viewer_urls)}")
        selected_urls = random.sample(all_viewer_urls, min(len(all_viewer_urls), count))

        results = []
        need_direct = self.config.get("return_type", 3) in [1, 3]

        for v_url in selected_urls:
            d_url = None
            album_name = None
            album_url = None
            # 总是尝试解析更多信息（即使不需直链，也要相册）
            d_url, album_name, album_url = await self._resolve_image_info(v_url, headers)
            
            results.append({
                "viewer_url": v_url,
                "direct_url": d_url,
                "album_name": album_name,
                "album_url": album_url
            })

        return results, "success"

    def _parse_gallery_links(self, html, base_url):
        soup = BeautifulSoup(html, 'html.parser')
        links = set()
        
        for a in soup.find_all('a', class_='image-container'):
            href = a.get('href')
            if href:
                links.add(urljoin(base_url, href))
        
        if not links:
            matches = re.findall(r'https://ibb\.co/[a-zA-Z0-9]{3,}', html)
            links.update(matches)
            
        return list(links)
    
    async def _download_for_base64(self, url: str, headers: dict) -> str | None:
        """下载 GIF 到内存，返回 base64 字符串（用于 File.fromBase64）"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=60) as resp:
                    if resp.status != 200:
                        logger.warning(f"下载 GIF 失败 {resp.status}: {url}")
                        return None
                    
                    data = await resp.read()
                    if len(data) < 10 * 1024:  # 小于 10KB 可能是预览，放弃
                        logger.warning(f"GIF 文件太小（可能是静态预览）: {len(data)} bytes, {url}")
                        return None
                    
                    base64_str = base64.b64encode(data).decode('utf-8')
                    logger.info(f"GIF 下载成功，转 base64 长度 {len(base64_str)}: {url}")
                    return base64_str
        except Exception as e:
            logger.error(f"下载 base64 失败: {url} - {str(e)}")
            return None
    
    async def _resolve_image_info(self, viewer_url, headers):
        domain = urlparse(viewer_url).netloc
        if "ibb.co" not in domain and "imgbb.com" not in domain:
            logger.debug(f"Invalid domain: {viewer_url}")
            return None, None, None

        html, _ = await self._request("GET", viewer_url, headers=headers)
        if not html:
            return None, None, None
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # ★ 只信任 og:image，这是完整动画源，不要再搜其他 .gif 了
        direct_url = None
        meta = soup.find("meta", property="og:image")
        if meta and "content" in meta.attrs:
            og_url = meta["content"].strip()
            if og_url.lower().endswith('.gif'):
                direct_url = og_url
                logger.info(f"使用 og:image 完整 GIF 链接: {direct_url}")
            else:
                logger.warning(f"og:image 不是 GIF，放弃: {og_url}")
                direct_url = None  # 强制不 fallback
        
        # 如果 og:image 失败，直接返回 None，不再尝试其他
        if not direct_url:
            logger.info(f"og:image 无效，不再尝试其他链接: {viewer_url}")
        
        # 相册信息（不变）
        album_name = None
        album_url = None
        added_texts = soup.find_all(string=re.compile(r'(Added to|已添加到了?)', re.I))
        for text in added_texts:
            parent = text.find_parent('a')
            if parent and 'href' in parent.attrs:
                href = parent['href']
                if '/album/' in href:
                    cleaned = re.sub(r'^(Added to|已添加到了?)\s+', '', text.strip(), flags=re.I)
                    album_name = cleaned.split('—')[0].strip()
                    album_url = urljoin(viewer_url, href)
                    break
        
        return direct_url, album_name, album_url

    async def _send_result(self, event, results, username):
        r_type = self.config.get("return_type", 3)  # ← 必须缩进 4 个空格
        chain = [Plain(f"🖼️ **用户 {username} 的图片** (GIF 请点链接查看动画)\n")]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        if self.config.get("cookie"):
            headers["Cookie"] = self.config.get("cookie").strip()

        for item in results:
            v_url = item["viewer_url"]
            d_url = item["direct_url"]
            album_name = item.get("album_name")
            album_url = item.get("album_url")

            album_info = ""
            if album_name:
                album_info = f"[{album_name}]"
                if album_url:
                    album_info += f" {album_url} → "
                else:
                    album_info += " → "
            else:
                album_info = "(无相册) → "

            is_gif = d_url and d_url.lower().endswith(('.gif', '.GIF'))

            if is_gif:
                chain.append(Plain(f"🔗 GIF 动画（点开查看完整播放）：{v_url}\n"))
                if d_url:
                    chain.append(Plain(f"直链预览（可能先静态）：{d_url}\n"))
            else:
                if d_url:
                    chain.append(Image.fromURL(d_url))
                chain.append(Plain(f"🔗 {album_info}查看原图：{v_url}\n"))

        yield event.chain_result(chain)

    # ==========================
    #  指令集
    # ==========================
    @filter.command("imgbb_get")
    async def get_user_img(self, event: AstrMessageEvent, username: str):
        '''抓取指定用户的图片'''
        count = self.config.get("fetch_count", 1)
        yield event.plain_result(f"🔍 正在抓取 {username}...")
        results, msg = await self._fetch_user_images(username)
        if not results:
            yield event.plain_result(f"❌ 失败: {msg}")
        else:
            async for msg in self._send_result(event, results, username):
                yield msg

    @filter.command("imgbb_rand")
    async def get_sub_rand(self, event: AstrMessageEvent):
        '''随机抓取订阅用户的图片'''
        chat_id = str(event.get_sender_id())
        subs = self.data["subs"].get(chat_id, [])
        if not subs:
            yield event.plain_result("❌ 当前无订阅")
            return
        lucky_user = random.choice(subs)
        yield event.plain_result(f"🎲 选中: {lucky_user}")
        
        results, msg = await self._fetch_user_images(lucky_user)
        if not results:
            yield event.plain_result(f"❌ 失败: {msg}")
        else:
            async for msg in self._send_result(event, results, lucky_user):
                yield msg

    @filter.command("imgbb_sub")
    async def subscribe(self, event: AstrMessageEvent, username: str):
        chat_id = str(event.get_sender_id())
        async with self.data_lock:
            if chat_id not in self.data["subs"]:
                self.data["subs"][chat_id] = []
            if username not in self.data["subs"][chat_id]:
                self.data["subs"][chat_id].append(username)
                await self._save_data()
                logger.info(f"订阅 {username} 成功，已保存 data.json")
                yield event.plain_result(f"✅ 已订阅 {username}")
            else:
                yield event.plain_result(f"⚠️ 已存在")

    @filter.command("imgbb_unsub")
    async def unsubscribe(self, event: AstrMessageEvent, username: str):
        chat_id = str(event.get_sender_id())
        async with self.data_lock:
            subs = self.data["subs"].get(chat_id, [])
            if username in subs:
                subs.remove(username)
                await self._save_data()
                logger.info(f"取消订阅 {username} 成功，已保存 data.json")
                yield event.plain_result(f"✅ 已取订 {username}")
            else:
                yield event.plain_result("❌ 未订阅")
            
    @filter.command("imgbb_list")
    async def list_subs(self, event: AstrMessageEvent):
        '''查看订阅列表'''
        chat_id = str(event.get_sender_id())
        subs = self.data["subs"].get(chat_id, [])
        if subs:
            msg = ["📋 订阅列表"] + [f"- {u}" for u in subs]
            yield event.plain_result("\n".join(msg))
        else:
            yield event.plain_result("📭 无订阅")
