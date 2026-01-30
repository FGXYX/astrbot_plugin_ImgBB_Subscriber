import aiohttp
import asyncio
import base64
import json
import os
import random
import re
import ssl
import shutil
import logging
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from astrbot.api.all import Context, Star, register, AstrMessageEvent
from astrbot.api.event import filter
from astrbot.api.message_components import Image, Plain


# ==========================================
# 0. 自定义日志过滤器
# ==========================================
class AstrBotLogFilter(logging.Filter):
    """
    专门用于修复 AstrBot 日志缺失自定义字段的问题
    """

    def __init__(self, plugin_tag, version_tag):
        super().__init__()
        self.plugin_tag = plugin_tag
        self.version_tag = version_tag

    def filter(self, record):
        # 1. 注入插件标签 (KeyError: 'plugin_tag')
        record.plugin_tag = self.plugin_tag

        # 2. 注入版本标签 (KeyError: 'astrbot_version_tag')
        # 这里我们填入插件的版本号，在日志里显示也很合理
        record.astrbot_version_tag = self.version_tag

        # 3. 注入短日志等级 (KeyError: 'short_levelname')
        level_map = {
            "DEBUG": "DBUG",
            "INFO": "INFO",
            "WARNING": "WARN",
            "ERROR": "ERRO",
            "CRITICAL": "FATL"
        }
        record.short_levelname = level_map.get(record.levelname, record.levelname[:4])
        return True


@register("ImgBB_Subscriber", "FGXYX", "ImgBB全能助手", "1.1.0")
class ImgBBPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # ==========================================
        # 1. 配置日志系统
        # ==========================================
        self.logger = logging.getLogger("astrbot.plugin.imgbb")
        # 清除可能存在的旧 filter 防止重复叠加
        for f in list(self.logger.filters):
            if isinstance(f, AstrBotLogFilter):
                self.logger.removeFilter(f)

        # 添加补全过滤器，传入插件名和版本号
        # 这样日志就会显示为 [ImgBB] [INFO] [v3.2.4] ...
        self.logger.addFilter(AstrBotLogFilter("ImgBB", "v3.2.4"))

        # ==========================================
        # 2. 路径定义 (数据与代码分离)
        # ==========================================
        root_dir = os.getcwd()
        self.save_dir = os.path.join(root_dir, "data", "plugin_data", "astrbot_plugin_ImgBB_Subscriber")
        self.data_path = os.path.join(self.save_dir, "data.json")
        self.old_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

        # ==========================================
        # 3. 初始化与数据迁移
        # ==========================================
        self.data_lock = asyncio.Lock()
        self._init_storage()
        self.data = self._load_data()

    def _init_storage(self):
        """初始化存储目录并执行迁移"""
        # 1. 确保新目录存在
        if not os.path.exists(self.save_dir):
            try:
                os.makedirs(self.save_dir)
                self.logger.info(f"创建数据目录: {self.save_dir}")
            except Exception as e:
                self.logger.error(f"创建数据目录失败: {e}")

        # 2. 检测是否需要迁移
        if not os.path.exists(self.data_path) and os.path.exists(self.old_data_path):
            self.logger.warning("检测到旧版数据文件，正在迁移至 data/plugin_data/ ...")
            try:
                shutil.copy2(self.old_data_path, self.data_path)
                self.logger.info(f"✅ 数据迁移成功！新路径: {self.data_path}")
                os.rename(self.old_data_path, self.old_data_path + ".bak")
            except Exception as e:
                self.logger.error(f"❌ 数据迁移失败: {e}，将使用空数据初始化。")

    def _load_data(self):
        if not os.path.exists(self.data_path):
            self._save_data_sync({"subs": {}})
            return {"subs": {}}
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载数据失败: {e}")
            return {"subs": {}}

    def _save_data_sync(self, data):
        """同步保存 (初始化用)"""
        try:
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"数据写入失败: {e}")

    async def _save_data_async(self):
        """异步保存 (运行时用)"""
        async with self.data_lock:
            try:
                await asyncio.to_thread(self._save_data_sync, self.data)
            except Exception as e:
                self.logger.error(f"异步保存失败: {e}")

    # --- 网络辅助函数 ---
    def _create_ssl_context(self):
        return ssl.create_default_context()

    def _get_proxy(self):
        p = self.config.get("http_proxy")
        if p and not p.startswith(("http://", "https://")):
            return f"http://{p}"
        return p

    # ==========================
    #  功能模块 1: 图片上传
    # ==========================
    @filter.command("upload")
    async def upload_image(self, event: AstrMessageEvent):
        '''上传图片到 ImgBB'''
        api_key = self.config.get("api_key")
        if not api_key:
            yield event.plain_result("❌ 配置错误：缺少 API Key")
            return

        target_img = None
        for component in event.message_obj.message:
            if isinstance(component, Image):
                target_img = component
                break

        if not target_img:
            yield event.plain_result("❌ 请在发送图片时附带 `/upload` 命令")
            return

        yield event.plain_result("☁️ 正在处理...")

        try:
            img_data = await self._download_image(target_img)
            if not img_data:
                yield event.plain_result("❌ 图片下载失败")
                return

            if len(img_data) > 10 * 1024 * 1024:
                yield event.plain_result("❌ 图片过大 (>10MB)")
                return

            b64_data = base64.b64encode(img_data).decode('utf-8')
        except Exception as e:
            self.logger.error(f"处理异常: {e}")
            yield event.plain_result("❌ 处理出错")
            return

        try:
            url = "https://api.imgbb.com/1/upload"
            payload = {"key": api_key, "image": b64_data}
            proxy = self._get_proxy()
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=payload, proxy=proxy) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"❌ HTTP {resp.status}")
                        return

                    res_json = await resp.json()
                    if res_json.get("success"):
                        data = res_json.get("data", {})
                        img_url = data.get("url") or data.get("display_url")
                        yield event.plain_result("✅ 上传成功！")
                        yield event.plain_result(f"🔗 直链: {img_url}")
                        yield event.plain_result(f"Markdown: ![]({img_url})")
                    else:
                        err = res_json.get("error", {}).get("message", "未知错误")
                        yield event.plain_result(f"❌ API 报错: {err}")

        except asyncio.TimeoutError:
            yield event.plain_result("❌ 上传超时")
        except Exception as e:
            self.logger.error(f"上传异常: {e}")
            yield event.plain_result("❌ 网络请求失败")

    async def _download_image(self, img_component: Image):
        if img_component.path and os.path.exists(img_component.path):
            with open(img_component.path, "rb") as f:
                return f.read()

        if img_component.url:
            parsed = urlparse(img_component.url)
            if parsed.scheme not in ("http", "https"):
                return None

            proxy = self._get_proxy()
            timeout = aiohttp.ClientTimeout(total=15)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(img_component.url, proxy=proxy) as resp:
                        if resp.status == 200:
                            return await resp.read()
            except Exception as e:
                self.logger.error(f"下载失败: {e}")
        return None

    # ==========================
    #  功能模块 2: 订阅与抓取
    # ==========================
    async def _fetch_user_images(self, username):
        count = self.config.get("fetch_count", 1)
        proxy = self._get_proxy()
        cookie = self.config.get("cookie")
        base_url = f"https://{username}.imgbb.com/"

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if cookie:
            headers["Cookie"] = cookie.replace("\n", "").replace("\r", "")

        ssl_ctx = self._create_ssl_context()
        timeout = aiohttp.ClientTimeout(total=20)

        try:
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout, connector=connector) as session:
                try:
                    async with session.get(base_url, proxy=proxy) as resp:
                        if resp.status != 200:
                            return None, f"主页 HTTP {resp.status}"
                        html = await resp.text()
                except Exception as e:
                    return None, f"主页请求错误: {type(e).__name__}"

                soup = BeautifulSoup(html, 'html.parser')
                links = soup.find_all('a', class_='image-container')

                viewer_urls = []
                for a in links:
                    href = a.get('href')
                    if href:
                        viewer_urls.append(urljoin(base_url, href))

                if not viewer_urls:
                    matches = re.findall(r'https://ibb\.co/[a-zA-Z0-9]{5,}', html)
                    viewer_urls = list(set(matches))

                if not viewer_urls:
                    return None, "未找到图片"

                selected_urls = random.sample(viewer_urls, min(len(viewer_urls), count))
                results = []
                r_type = self.config.get("return_type", 3)
                need_direct = r_type in [1, 3]

                for v_url in selected_urls:
                    d_url = None
                    if need_direct:
                        d_url = await self._get_direct_image(session, v_url, proxy)
                    results.append({"viewer_url": v_url, "direct_url": d_url})

                return results, "success"
        except Exception as e:
            self.logger.error(f"抓取错误: {e}")
            return None, "内部错误"

    async def _get_direct_image(self, session, viewer_url, proxy):
        try:
            async with session.get(viewer_url, proxy=proxy) as resp:
                if resp.status != 200: return None
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                meta = soup.find("meta", property="og:image")
                if meta: return meta["content"]
                link = soup.find("link", rel="image_src")
                if link: return link["href"]
                return None
        except:
            return None

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
                    chain.append(Plain(f"[无法解析] {v_url}\n"))
            elif r_type == 2:
                chain.append(Plain(f"🔗 {v_url}\n"))
            else:
                if d_url: chain.append(Image.fromURL(d_url))
                chain.append(Plain(f"🔗 查看: {v_url}\n"))
        yield event.chain_result(chain)

    # --- 指令集 ---
    @filter.command("imgbb_get")
    async def get_user_img(self, event: AstrMessageEvent, username: str):
        yield event.plain_result(f"🔍 正在抓取 {username}...")
        results, msg = await self._fetch_user_images(username)
        if not results:
            yield event.plain_result(f"❌ 失败: {msg}")
        else:
            async for msg in self._send_result(event, results, username):
                yield msg

    @filter.command("imgbb_rand")
    async def get_sub_rand(self, event: AstrMessageEvent):
        chat_id = str(event.get_sender_id())
        subs = self.data["subs"].get(chat_id, [])
        if not subs:
            yield event.plain_result("❌ 无订阅")
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
                await self._save_data_async()
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
                await self._save_data_async()
                yield event.plain_result(f"✅ 已取订 {username}")
            else:
                yield event.plain_result("❌ 未订阅")

    @filter.command("imgbb_list")
    async def list_subs(self, event: AstrMessageEvent):
        chat_id = str(event.get_sender_id())
        subs = self.data["subs"].get(chat_id, [])
        if subs:
            msg = ["📋 订阅列表"] + [f"- {u}" for u in subs]
            yield event.plain_result("\n".join(msg))
        else:
            yield event.plain_result("📭 无订阅")
