"""
高德地图 REST API 工具封装
直接调用高德官方 HTTP 接口，无需 MCP 中转
"""
import os
import requests
from langchain_core.tools import tool
from utils.logger_handler import logger

# 从环境变量读取高德 Web 服务 Key
AMAP_KEY = os.environ.get("AMAP_API_KEY", "")


def _check_key():
    """检查 Key 是否配置"""
    if not AMAP_KEY:
        return "[错误] 高德地图 API Key 未配置，请在系统环境变量 AMAP_API_KEY 中设置"
    return None


@tool(description="查询指定城市的实时天气信息，入参 city 为城市名称（如：深圳、北京、上海）")
def amap_weather(city: str) -> str:
    """查询城市天气"""
    err = _check_key()
    if err:
        return err

    try:
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {"key": AMAP_KEY, "city": city, "extensions": "base"}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "1":
            return f"天气查询失败：{data.get('info', '未知错误')}"

        lives = data.get("lives", [])
        if not lives:
            return f"未找到城市 {city} 的天气信息"

        w = lives[0]
        return (
            f"【{w.get('city')}实时天气】\n"
            f"天气：{w.get('weather')}\n"
            f"温度：{w.get('temperature')}°C\n"
            f"风向：{w.get('winddirection')}\n"
            f"风力：{w.get('windpower')}级\n"
            f"湿度：{w.get('humidity')}%\n"
            f"发布时间：{w.get('reporttime')}"
        )
    except Exception as e:
        logger.error(f"[高德天气] 查询失败: {e}")
        return f"天气查询出错: {str(e)}"


@tool(description="搜索指定地点或POI，入参 keywords 为关键词（如：扫地机器人维修点、加油站），city 为城市名（可选，如：深圳）")
def amap_poi_search(keywords: str, city: str = "") -> str:
    """搜索POI地点"""
    err = _check_key()
    if err:
        return err

    try:
        url = "https://restapi.amap.com/v3/place/text"
        params = {
            "key": AMAP_KEY,
            "keywords": keywords,
            "offset": 5,
            "page": 1,
            "extensions": "all"
        }
        if city:
            params["city"] = city

        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "1":
            return f"搜索失败：{data.get('info', '未知错误')}"

        pois = data.get("pois", [])
        if not pois:
            return f"未找到与 '{keywords}' 相关的地点"

        results = []
        for i, p in enumerate(pois[:5], 1):
            name = p.get("name", "未知")
            address = p.get("address", "地址不详")
            tel = p.get("tel", "无电话")
            location = p.get("location", "")
            results.append(
                f"{i}. {name}\n"
                f"   地址：{address}\n"
                f"   电话：{tel}\n"
                f"   坐标：{location}"
            )

        return "【搜索结果】\n" + "\n\n".join(results)
    except Exception as e:
        logger.error(f"[高德POI] 搜索失败: {e}")
        return f"搜索出错: {str(e)}"


@tool(description="地理编码：将地址转换为经纬度坐标，入参 address 为详细地址（如：北京市朝阳区望京街9号）")
def amap_geocode(address: str) -> str:
    """地址转坐标"""
    err = _check_key()
    if err:
        return err

    try:
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {"key": AMAP_KEY, "address": address}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "1":
            return f"地理编码失败：{data.get('info', '未知错误')}"

        geocodes = data.get("geocodes", [])
        if not geocodes:
            return f"无法解析地址：{address}"

        g = geocodes[0]
        return (
            f"【地址解析结果】\n"
            f"格式化地址：{g.get('formatted_address')}\n"
            f"经纬度：{g.get('location')}\n"
            f"省：{g.get('province')}\n"
            f"市：{g.get('city')}\n"
            f"区：{g.get('district')}"
        )
    except Exception as e:
        logger.error(f"[高德地理编码] 失败: {e}")
        return f"地理编码出错: {str(e)}"


@tool(description="路径规划：查询从起点到终点的步行/驾车路线，入参 origin 和 destination 为地址或经纬度坐标，mode 为出行方式（walking 步行 或 driving 驾车，默认 walking）")
def amap_route(origin: str, destination: str, mode: str = "walking") -> str:
    """路径规划"""
    err = _check_key()
    if err:
        return err

    try:
        if mode == "driving":
            url = "https://restapi.amap.com/v3/direction/driving"
        else:
            url = "https://restapi.amap.com/v3/direction/walking"

        params = {
            "key": AMAP_KEY,
            "origin": origin,
            "destination": destination,
            "extensions": "all"
        }

        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") != "1":
            return f"路径规划失败：{data.get('info', '未知错误')}"

        route = data.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return "未找到可行路线"

        p = paths[0]
        steps = p.get("steps", [])
        step_text = "\n".join([
            f"  {i+1}. {s.get('instruction', '')}"
            for i, s in enumerate(steps[:5])
        ])

        return (
            f"【路线规划结果】\n"
            f"距离：{p.get('distance', '未知')} 米\n"
            f"预计时间：{p.get('duration', '未知')} 秒\n"
            f"费用：{p.get('tolls', '0')} 元\n"
            f"主要路线：\n{step_text}\n"
            f"（共 {len(steps)} 个路段）"
        )
    except Exception as e:
        logger.error(f"[高德路线] 规划失败: {e}")
        return f"路线规划出错: {str(e)}"