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


@register("ImgBB_Subscriber", "FGXYX", "ImgBB助手", "1.0.0")
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
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump({"subs": {}}, f)
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

    # ==========================
    #  功能模块 1: 图片上传
    # ==========================
    @filter.command("up")
    async def upload_image(self, event: AstrMessageEvent):
        '''上传图片到 ImgBB'''
        api_key = self.config.get("api_key")
        if not api_key:
            yield event.plain_result("❌ 未配置 API Key！请在插件配置中填写。")
            return

        # 1. 寻找图片
        target_img = None
        for component in event.message_obj.message:
            if isinstance(component, Image):
                target_img = component
                break

        if not target_img:
            yield event.plain_result("❌ 请在发送图片时附带 `/upload` 命令。")
            return

        yield event.plain_result("☁️ 正在上传...")

        # 2. 下载并处理
        try:
            img_data = await self._download_image(target_img)
            if not img_data:
                yield event.plain_result("❌ 图片下载失败 (请检查代理设置)")
                return
            b64_data = base64.b64encode(img_data).decode('utf-8')
        except Exception as e:
            yield event.plain_result(f"❌ 处理出错: {e}")
            return

        # 3. 上传到 API
        try:
            url = "https://api.imgbb.com/1/upload"
            payload = {"key": api_key, "image": b64_data}
            proxy = self.config.get("http_proxy")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload, proxy=proxy) as resp:
                    res_json = await resp.json()

                    if resp.status == 200 and res_json.get("success"):
                        data = res_json["data"]
                        img_url = data["url"]
                        msg = [
                            Plain("✅ **上传成功！**\n"),
                            Plain(f"🔗 **直链**: {img_url}\n"),
                            Plain(f"Markdown: `![]({img_url})`")
                        ]
                        yield event.chain_result(msg)
                    else:
                        err = res_json.get("error", {}).get("message", "未知错误")
                        yield event.plain_result(f"❌ ImgBB 报错: {err}")
        except Exception as e:
            yield event.plain_result(f"❌ 上传请求失败: {e}")

    async def _download_image(self, img_component: Image):
        if img_component.path and os.path.exists(img_component.path):
            with open(img_component.path, "rb") as f:
                return f.read()
        if img_component.url:
            proxy = self.config.get("http_proxy")
            async with aiohttp.ClientSession() as session:
                async with session.get(img_component.url, proxy=proxy) as resp:
                    if resp.status == 200:
                        return await resp.read()
        return None

    # ==========================
    #  功能模块 2: 订阅与抓取
    # ==========================
    async def _fetch_user_images(self, username):
        count = self.config.get("fetch_count", 1)
        proxy = self.config.get("http_proxy")
        cookie = self.config.get("cookie")
        url = f"https://{username}.imgbb.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        if cookie:
            headers["Cookie"] = cookie

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, proxy=proxy, verify_ssl=False) as resp:
                    if resp.status != 200:
                        return None, f"HTTP {resp.status}"
                    html = await resp.text()

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
            async with session.get(viewer_url, proxy=proxy, verify_ssl=False) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                meta = soup.find("meta", property="og:image")
                if meta:
                    return meta["content"]
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
                    chain.append(Plain(f"[解析失败] {v_url}\n"))
            elif r_type == 2:
                chain.append(Plain(f"🔗 {v_url}\n"))
            else:
                if d_url:
                    chain.append(Image.fromURL(d_url))
                chain.append(Plain(f"🔗 {v_url}\n"))

        yield event.chain_result(chain)

    @filter.command("imgbb_get")
    async def get_user_img(self, event: AstrMessageEvent, username: str):
        '''根据作者来获取图片'''
        count = self.config.get("fetch_count", 1)
        yield event.plain_result(f"🔍 正在抓取 {username} 的 {count} 张图片...")
        results, msg = await self._fetch_user_images(username)
        if not results:
            yield event.plain_result(f"❌ 失败: {msg}")
        else:
            async for msg in self._send_result(event, results, username):
                yield msg

    @filter.command("imgbb_rand")
    async def get_sub_rand(self, event: AstrMessageEvent):
        '''从订阅列表中随机获取图片'''
        chat_id = event.get_sender_id()
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
        '''订阅ImgBB作者'''
        chat_id = event.get_sender_id()
        if chat_id not in self.data["subs"]:
            self.data["subs"][chat_id] = []
        if username not in self.data["subs"][chat_id]:
            self.data["subs"][chat_id].append(username)
            self._save_data()
        yield event.plain_result(f"✅ 已订阅 {username}")

    @filter.command("imgbb_unsub")
    async def unsubscribe(self, event: AstrMessageEvent, username: str):
        '''取消订阅'''
        chat_id = event.get_sender_id()
        subs = self.data["subs"].get(chat_id, [])
        if username in subs:
            subs.remove(username)
            self._save_data()
            yield event.plain_result(f"✅ 已取订 {username}")
        else:
            yield event.plain_result("❌ 未订阅")

    @filter.command("imgbb_list")
    async def list_subs(self, event: AstrMessageEvent):
        '''查看订阅列表'''
        chat_id = event.get_sender_id()
        subs = self.data["subs"].get(chat_id, [])
        if subs:
            msg = ["📋 订阅列表"] + [f"- {u}" for u in subs]
            yield event.plain_result("\n".join(msg))
        else:
            yield event.plain_result("📭 无订阅")
