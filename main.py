import asyncio
import base64
import json
import os
import random
import ssl
import re
from urllib.parse import urljoin, urlparse
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup

# 【关键修复】：直接从框架导入 logger
from astrbot.api.all import Context, Star, register, AstrMessageEvent, logger
from astrbot.api.event import filter
from astrbot.api.message_components import Image, Plain

@register("ImgBB_Subscriber", "FGXYX", "ImgBB助手", "3.3.1")
class ImgBBPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # ==========================================
        # 1. 路径定义
        # ==========================================
        self.plugin_dir = Path(__file__).parent
        self.data_file = self.plugin_dir / "data.json"
        
        # ==========================================
        # 2. 初始化并发锁
        # ==========================================
        self.data_lock = asyncio.Lock()
        self.data = {}
        
        # 异步初始化数据加载
        self._load_data_sync()

    def _load_data_sync(self):
        """同步加载数据（仅初始化使用）"""
        if not self.data_file.exists():
            self._save_data_internal({"subs": {}})
            self.data = {"subs": {}}
        else:
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"数据文件损坏，已重置: {e}")
                self.data = {"subs": {}}

    async def _save_data(self):
        """异步保存数据（运行时使用，带锁）"""
        async with self.data_lock:
            try:
                await asyncio.to_thread(self._save_data_internal, self.data)
            except Exception as e:
                logger.error(f"保存数据失败: {e}")

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
        base_url = f"https://{username}.imgbb.com/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        if self.config.get("cookie"):
            headers["Cookie"] = self.config.get("cookie").strip()

        html, msg = await self._request("GET", base_url, headers=headers)
        if not html:
            return None, msg

        viewer_urls = self._parse_gallery_links(html, base_url)
        if not viewer_urls:
            return None, "未找到图片 (可能是私有相册或 Cookie 失效)"

        selected_urls = random.sample(viewer_urls, min(len(viewer_urls), count))
        
        results = []
        need_direct = self.config.get("return_type", 3) in [1, 3]
        
        for v_url in selected_urls:
            d_url = None
            if need_direct:
                d_url = await self._resolve_direct_image(v_url, headers)
            results.append({"viewer_url": v_url, "direct_url": d_url})
            
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

    async def _resolve_direct_image(self, viewer_url, headers):
        domain = urlparse(viewer_url).netloc
        if "ibb.co" not in domain and "imgbb.com" not in domain:
            return None

        html, _ = await self._request("GET", viewer_url, headers=headers)
        if not html: return None
        
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find("meta", property="og:image")
        return meta["content"] if meta else None

    async def _send_result(self, event, results, username):
        r_type = self.config.get("return_type", 3)
        chain = [Plain(f"🖼️ **用户 {username} 的图片**\n")]

        for item in results:
            v_url = item["viewer_url"]
            d_url = item["direct_url"]

            if r_type == 1:
                if d_url:
                    chain.append(Image.fromURL(d_url))
                else:
                    chain.append(Plain(f"[解析直链失败] {v_url}\n"))
            elif r_type == 2:
                chain.append(Plain(f"🔗 {v_url}\n"))
            else:
                if d_url:
                    chain.append(Image.fromURL(d_url))
                chain.append(Plain(f"🔗 {v_url}\n"))

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
        '''订阅用户'''
        chat_id = str(event.get_sender_id())
        async with self.data_lock:
            if chat_id not in self.data["subs"]:
                self.data["subs"][chat_id] = []
            if username not in self.data["subs"][chat_id]:
                self.data["subs"][chat_id].append(username)
                await self._save_data()
                yield event.plain_result(f"✅ 已订阅 {username}")
            else:
                yield event.plain_result(f"⚠️ 已存在")

    @filter.command("imgbb_unsub")
    async def unsubscribe(self, event: AstrMessageEvent, username: str):
        '''取消订阅'''
        chat_id = str(event.get_sender_id())
        async with self.data_lock:
            subs = self.data["subs"].get(chat_id, [])
            if username in subs:
                subs.remove(username)
                await self._save_data()
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