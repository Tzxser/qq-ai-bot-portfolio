import asyncio
import random
import time
from types import SimpleNamespace


TEMPLATES = (
    "{mentions} 欢迎加入 ACM！算法、代码和学习路线都可以 @我问；培训、报名等具体安排请以管理通知为准。",
    "{mentions} 新队友已到位～从第一段程序到第一道通过的题，有问题都可以慢慢问。",
    "{mentions} 欢迎！卡在报错里也没关系，带上代码、报错和尝试过程来找我。",
    "{mentions} 很高兴在这里遇见你！想学算法、做项目或了解社团，都可以 @我。",
    "{mentions} 欢迎来到 ACM！基础薄弱也可以一步一步学，先找到愿意开始的方向。",
    "{mentions} 队伍又多了一位伙伴！有问题不用憋着，@我说清楚哪里卡住了。",
    "{mentions} 欢迎加入！这里先不比谁会得多，先把不懂的弄明白。",
    "{mentions} 初次见面，欢迎～我是群里的 AI 答疑助手，不是人工管理员。",
    "{mentions} 新成员签到成功——这里说的是欢迎，不是正式活动签到哦。",
    "{mentions} 欢迎！不用一次学完所有东西，先从一个小问题开始。",
    "{mentions} 你好，新队友！题目不会做时，可以先告诉我题意和想到哪一步。",
    "{mentions} 欢迎加入 ACM！愿你的疑问越来越清楚，报错越来越少。",
    "{mentions} 欢迎来到群里～先熟悉一下环境也完全可以，学习问题随时 @我。",
    "{mentions} 很高兴又多一位同行伙伴！代码、路线或部门分工都可以问我。",
    "{mentions} 欢迎！遇到问题时，把哪里不懂和已经试过什么说清楚就能开始。",
    "{mentions} ACM 新队友到站！学习不必着急赶进度，有疑问就 @我。",
    "{mentions} 欢迎加入～算法题和开发问题都可以从最基础的地方问起。",
    "{mentions} 你好呀！我是群里的 AI 答疑助手，需要学习帮助可以 @我。",
    "{mentions} 欢迎！第一天可以先了解方向，不需要立即给自己定很难的目标。",
    "{mentions} 新伙伴，欢迎来到 ACM！代码问题最好附上文字和报错，方便一起定位。",
    "{mentions} 欢迎加入我们的交流空间！技术问题可以直接 @我，别怕问基础内容。",
    "{mentions} 很高兴见到你～这里可以从一个小问题开始，具体安排请向管理核实。",
    "{mentions} 欢迎新队友！遇到卡点，先把问题描述清楚就已经前进了一步。",
    "{mentions} 欢迎加入 ACM！慢慢认识队友，也慢慢找到自己的方向。",
)


class WelcomeService:
    def __init__(self, settings, store, limiter, sender, metrics=None):
        self.settings, self.store, self.limiter, self.sender = settings, store, limiter, sender
        self.metrics = metrics if metrics is not None else {}
        self.pending = {}
        self.tasks = {}
        self.recent_templates = {}

    def _enabled(self, notice):
        enabled = bool(getattr(self.settings, "group_welcome_enabled", False))
        allowed = getattr(self.settings, "allowed_group_ids", ())
        return enabled and str(notice.group_id) in tuple(allowed or ())

    async def _allow(self, key, seconds):
        method = getattr(self.limiter, "allow_key", None)
        if method is not None:
            return bool(await method(key, seconds))
        return bool(await self.limiter.allow(key))

    async def handle(self, notice):
        if not self._enabled(notice):
            self.metrics["welcome_ignored"] = self.metrics.get("welcome_ignored", 0) + 1
            return
        if time.time() - notice.timestamp > getattr(self.settings, "welcome_stale_seconds", 180):
            self.metrics["welcome_stale"] = self.metrics.get("welcome_stale", 0) + 1
            return
        if not await self.store.claim(notice.event_id, f"welcome:{notice.group_id}"):
            self.metrics["welcome_duplicate"] = self.metrics.get("welcome_duplicate", 0) + 1
            return
        if not await self._allow(f"welcome:{notice.group_id}:{notice.user_id}", 86400):
            self.metrics["welcome_duplicate"] = self.metrics.get("welcome_duplicate", 0) + 1
            return
        self.pending.setdefault(notice.group_id, []).append(notice)
        if notice.group_id not in self.tasks:
            self.tasks[notice.group_id] = asyncio.create_task(self._flush_later(notice.group_id))

    async def _flush_later(self, group_id):
        try:
            await asyncio.sleep(getattr(self.settings, "welcome_window", 20.0))
            notices = self.pending.pop(group_id, [])
            unique = []
            seen = set()
            for notice in notices:
                if notice.user_id not in seen:
                    seen.add(notice.user_id)
                    unique.append(notice)
            unique = unique[:5]
            if not unique:
                return
            # A membership probe is best effort; a failed probe is treated as
            # not sendable so stale welcomes are never replayed.
            members = []
            probe = getattr(self.sender, "member_in_group", None)
            for notice in unique:
                if probe is not None:
                    try:
                        if not await probe(group_id, notice.user_id):
                            continue
                    except Exception:
                        continue
                members.append(notice)
            if not members:
                self.metrics["welcome_member_gone"] = self.metrics.get("welcome_member_gone", 0) + 1
                return
            if not await self._allow(f"welcome-send:{group_id}", 30):
                self.metrics["welcome_rate_limited"] = self.metrics.get("welcome_rate_limited", 0) + 1
                return
            old = self.recent_templates.setdefault(group_id, [])
            choices = [i for i in range(len(TEMPLATES)) if i not in old[-5:]] or list(range(len(TEMPLATES)))
            template_id = random.choice(choices)
            old.append(template_id)
            mentions = " ".join(f"[at:{n.user_id}]" for n in members)
            if len(notices) > len(members) or len(notices) > 5:
                mentions += " 也欢迎这次一起加入的其他同学"
            text = TEMPLATES[template_id].format(mentions=mentions)
            target = SimpleNamespace(self_id=members[0].self_id, group_id=group_id, user_id="")
            segments = []
            for notice in members:
                segments.append({"type": "at", "data": {"qq": notice.user_id}})
            segments.append({"type": "text", "data": {"text": text.replace(mentions, "").lstrip()}})
            try:
                reply_id = await self.sender.send_segments(target, segments)
                recorder = getattr(self.store, "record_outbound", None)
                if recorder is not None:
                    await recorder(reply_id, target.self_id, group_id=group_id, event_key=f"welcome:{group_id}")
                self.metrics["welcome_sent"] = self.metrics.get("welcome_sent", 0) + 1
            except Exception:
                self.metrics["welcome_failed"] = self.metrics.get("welcome_failed", 0) + 1
        finally:
            self.tasks.pop(group_id, None)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.pending.clear()
