import aiohttp
import asyncio
import json
import os
import random
import re
from bs4 import BeautifulSoup
from astrbot.api.all import *
from astrbot.api.event import filter
from astrbot.api.message_components import Image, Plain


@register("imgbb_subscriber", "FGXYX", "ImgBB订阅助手", "1.0.0")
class ImgBBSubscriber(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_path = os.path.join(os.path.dirname(__file__), "data.json")
        self.data = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.data_path):
            with open(self.data_path, 'w', encoding='utf-8') as f: json.dump({"subs": {}}, f)
            return {"subs": {}}
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"subs": {}}

    def _save_data(self):
        with open(self.data_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # --- 核心爬虫 ---
    async def _fetch_user_images(self, username):
        count = self.config.get("fetch_count", 1)
        proxy = self.config.get("http_proxy")
        cookie = self.config.get("cookie")

        url = f"https://{username}.imgbb.com/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        if cookie: headers["Cookie"] = cookie

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, proxy=proxy, verify_ssl=False) as resp:
                    if resp.status != 200: return None, f"HTTP {resp.status}"
                    html = await resp.text()

                soup = BeautifulSoup(html, 'html.parser')
                links = soup.find_all('a', class_='image-container')
                viewer_urls = [a['href'] for a in links if 'href' in a.attrs]

                if not viewer_urls:
                    matches = re.findall(r'https://ibb\.co/[a-zA-Z0-9]+', html)
                    viewer_urls = list(set(matches))

                if not viewer_urls: return None, "未找到图片"

                selected_urls = random.sample(viewer_urls, min(len(viewer_urls), count))
                results = []

                # --- 修改点：这里使用数字判断 ---
                # 1:仅图片, 2:仅链接, 3:图片+链接
                # 所以 1 和 3 需要解析直链
                r_type = self.config.get("return_type", 3)
                need_direct = r_type in [1, 3]

                for v_url in selected_urls:
                    d_url = await self._get_direct_image(session, v_url, proxy) if need_direct else None
                    results.append({"viewer_url": v_url, "direct_url": d_url})

                return results, "success"
        except Exception as e:
            return None, str(e)

    async def _get_direct_image(self, session, viewer_url, proxy):
        try:
            async with session.get(viewer_url, proxy=proxy, verify_ssl=False) as resp:
                if resp.status != 200: return None
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                meta = soup.find("meta", property="og:image")
                if meta: return meta["content"]
                return None
        except:
            return None

    # --- 消息发送 ---
    async def _send_result(self, event, results, username):
        # --- 修改点：这里也改成数字判断 ---
        r_type = self.config.get("return_type", 3)
        chain = [Plain(f"🖼️ **用户 {username} 的图片**\n")]

        for item in results:
            v_url = item["viewer_url"]
            d_url = item["direct_url"]

            # 类型 1: 仅图片
            if r_type == 1:
                if d_url:
                    chain.append(Image.fromURL(d_url))
                else:
                    chain.append(Plain(f"[解析失败] {v_url}\n"))

            # 类型 2: 仅链接
            elif r_type == 2:
                chain.append(Plain(f"🔗 {v_url}\n"))

            # 类型 3 (或其它): 图片+链接
            else:
                if d_url: chain.append(Image.fromURL(d_url))
                chain.append(Plain(f"🔗 {v_url}\n"))

        yield event.chain_result(chain)

    # --- 指令 ---
    @filter.command("imgbb_get")
    async def get_user_img(self, event: AstrMessageEvent, username: str):
        '''获取用户图片'''
        count = self.config.get("fetch_count", 1)
        yield event.plain_result(f"🔍 正在抓取 {username} 的 {count} 张图片...")
        results, msg = await self._fetch_user_images(username)
        if not results:
            yield event.plain_result(f"❌ 失败: {msg}")
        else:
            async for msg in self._send_result(event, results, username): yield msg

    @filter.command("imgbb_rand")
    async def get_sub_rand(self, event: AstrMessageEvent):
        '''随机获取订阅图片'''
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
            async for msg in self._send_result(event, results, lucky_user): yield msg

    @filter.command("imgbb_sub")
    async def subscribe(self, event: AstrMessageEvent, username: str):
        chat_id = event.get_sender_id()
        if chat_id not in self.data["subs"]: self.data["subs"][chat_id] = []
        if username not in self.data["subs"][chat_id]:
            self.data["subs"][chat_id].append(username)
            self._save_data()
        yield event.plain_result(f"✅ 已订阅 {username}")

    @filter.command("imgbb_unsub")
    async def unsubscribe(self, event: AstrMessageEvent, username: str):
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
        subs = self.data["subs"].get(event.get_sender_id(), [])
        msg = ["📋 订阅列表"] + [f"- {u}" for u in subs] if subs else ["📭 无订阅"]
        yield event.plain_result("\n".join(msg))