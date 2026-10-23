"""发布：dry-run / webhook 两种渠道（借鉴 GeoLook「只接官方 API、永远手动触发」的纪律）。"""
import httpx


def publish_article(title: str, body: str, channel_name: str, channels: list) -> dict:
    """按渠道配置发布，返回 {url, detail}。"""
    cfg = next((c for c in channels if c.get("name") == channel_name), None)
    if cfg is None or cfg.get("type") != "webhook" or not cfg.get("webhook_url"):
        return {"url": "dry-run", "detail": "演练发布（dry-run）：已标记为已发布，未推送到外部渠道"}

    try:
        resp = httpx.post(
            cfg["webhook_url"],
            json={"title": title, "body": body, "channel": channel_name},
            timeout=30,
        )
        resp.raise_for_status()
        return {"url": cfg["webhook_url"], "detail": f"已推送至 {channel_name}，状态码 {resp.status_code}"}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"发布失败：{e}")
