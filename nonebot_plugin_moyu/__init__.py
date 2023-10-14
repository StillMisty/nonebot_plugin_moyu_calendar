
import re
from pathlib import Path

from typing import Any, Annotated

import httpx
from nonebot import get_bot, get_driver, logger, on_regex, require
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import RegexGroup
from nonebot.plugin import PluginMetadata

try:
    import ujson as json
except ModuleNotFoundError:
    import json

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

__usages__ = f'''
[摸鱼] 获取今日摸鱼日历
'''.strip()

__plugin_meta__ = PluginMetadata(
    name="摸鱼日历",
    description="摸鱼日历！每日摸鱼必备",
    usage=__usages__,
)



subscribe = Path(__file__).parent / "subscribe.json"

subscribe_list = json.loads(subscribe.read_text("utf-8")) if subscribe.is_file() else {}


def save_subscribe():
    subscribe.write_text(json.dumps(subscribe_list), encoding="utf-8")


driver = get_driver()


async def get_calendar() -> bytes:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        response = await client.get(
            "https://api.vvhan.com/api/moyu?type=image"
        )
        if response.is_error:
            raise ValueError(f"摸鱼日历获取失败，错误码：{response.status_code}")
        
        return response.content


@driver.on_startup
async def subscribe_jobs():
    for group_id, info in subscribe_list.items():
        scheduler.add_job(
            push_calendar,
            "cron",
            args=[group_id],
            id=f"moyu_calendar_{group_id}",
            replace_existing=True,
            hour=info["hour"],
            minute=info["minute"],
        )


async def push_calendar(group_id: str):
    bot = get_bot()
    try:
        moyu_img = await get_calendar()
    except Exception as e:
        logger.error(e)
    
    await bot.send_group_msg(
        group_id=int(group_id), message=MessageSegment.image(moyu_img)
    )


def calendar_subscribe(group_id: str, hour: str, minute: str) -> None:
    subscribe_list[group_id] = {"hour": hour, "minute": minute}
    save_subscribe()
    scheduler.add_job(
        push_calendar,
        "cron",
        args=[group_id],
        id=f"moyu_calendar_{group_id}",
        replace_existing=True,
        hour=hour,
        minute=minute,
    )
    logger.debug(f"群[{group_id}]设置摸鱼日历推送时间为：{hour}:{minute}")


moyu_matcher = on_regex("^摸鱼\s*(状态|设置|推送|禁用|关闭|帮助)?\s*(([01]?\d|2[0-3])[:：]([0-5]?\d)|all|ALL)?$",flags=re.I, priority=5, block=True)


@moyu_matcher.handle()
async def moyu(
    event: GroupMessageEvent, matcher: Matcher, args: Annotated[tuple[Any, ...], RegexGroup()]
):
    # 获取摸鱼参数
    parameter = args[0]
    
    match parameter:
        case None:
            # 只有摸鱼时
            try:
                moyu_img = await get_calendar()
            except Exception as e:
                logger.error(e)
                await matcher.finish(e)
            await matcher.finish(MessageSegment.image(moyu_img))
        case "状态":
            push_state = scheduler.get_job(f"moyu_calendar_{event.group_id}")
            moyu_state = "摸鱼日历状态：\n每日推送: " + ("已开启" if push_state else "已关闭")
            if push_state:
                group_id_info = subscribe_list[str(event.group_id)]
                moyu_state += (
                    f"\n推送时间: {group_id_info['hour']}:{group_id_info['minute']}"
                )
            await matcher.finish(moyu_state)
            
        case "设置" | "推送":
            # 检查参数是否存在
            if args[2] is None or args[3] is None:
                await matcher.finish("参数设置错误，应为：摸鱼 (设置|推送) 时:分")
                
            # 参数正确时
            calendar_subscribe(str(event.group_id), args[2], args[3])
            await matcher.finish(f"本群摸鱼日历推送时间设置成功：{args[2]}:{args[3]}")
        
        case "禁用" | "关闭":
            
            if args[1] is None:
                # 说明是只删当前的
                if str(event.group_id) not in subscribe_list.keys():
                    await matcher.finish("本群未开启摸鱼日历推送")
                
                del subscribe_list[str(event.group_id)]
                save_subscribe()
                scheduler.remove_job(f"moyu_calendar_{event.group_id}")
                await matcher.finish("本群摸鱼日历推送已禁用")
                
            if args[1] == "all" or args[1] == "ALL":
                # 删除所有摸鱼订阅
                for group in subscribe_list.keys():
                    scheduler.remove_job(f"moyu_calendar_{group}")
                subscribe_list.clear()
                save_subscribe()
                await matcher.finish("所有摸鱼日历推送已禁用")

        case "帮助":
            await matcher.finish('''可用参数：\n1、摸鱼 状态 【查看摸鱼日历推送状态】\n2、摸鱼 (设置|推送) 时:分 【设置当前群摸鱼日历推送时间】\n3、禁用 (禁用|关闭) (all|ALL) 【禁用摸鱼日历推送，不输入all则只禁用当前群反之禁用所有群】''')