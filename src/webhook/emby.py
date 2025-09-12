import logging
from typing import Any, Dict, Optional
from fastapi import Request, HTTPException, status
import os

from .base import BaseWebhook
from ..scraper_manager import ScraperManager
from .tasks import webhook_search_and_dispatch_task
from .utils.metadata_enhancer import enhance_webhook_metadata

logger = logging.getLogger(__name__)

class EmbyWebhook(BaseWebhook):

    async def handle(self, request: Request):
        # 处理器现在负责解析请求体。
        # Emby 通常发送 application/json。
        try:
            payload = await request.json()
        except Exception:
            logger.error("Emby Webhook: 无法解析请求体为JSON。")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请求体不是有效的JSON。")

        event_type = payload.get("Event")
        # 我们关心入库和播放开始的事件
        if event_type not in ["item.add", "library.new", "playback.start"]:
            logger.info(f"Webhook: 忽略非 'item.add', 'library.new' 或 'playback.start' 的事件 (类型: {event_type})")
            return

        item = payload.get("Item", {})
        if not item:
            logger.warning("Emby Webhook: 负载中缺少 'Item' 信息。")
            return

        item_type = item.get("Type")
        if item_type not in ["Episode", "Movie"]:
            logger.info(f"Webhook: 忽略非 'Episode' 或 'Movie' 的媒体项 (类型: {item_type})")
            return

        # 提取基本信息
        item_id = item.get("Id")
        year = item.get("ProductionYear")

        # 提取基础的 Provider IDs
        provider_ids = item.get("ProviderIds", {})
        basic_tmdb_id = provider_ids.get("Tmdb")
        basic_imdb_id = provider_ids.get("IMDB") # 修正：Emby 使用大写的 "IMDB"
        basic_tvdb_id = provider_ids.get("Tvdb")
        basic_douban_id = provider_ids.get("DoubanID") # Emby 可能使用 DoubanID
        basic_bangumi_id = provider_ids.get("Bangumi")

        logger.info(f"Emby Webhook: 基础元数据 - TMDB: {basic_tmdb_id}, IMDb: {basic_imdb_id}, TVDB: {basic_tvdb_id}, Douban: {basic_douban_id}, Bangumi: {basic_bangumi_id}")
        
        # 根据媒体类型分别处理
        if item_type == "Episode":
            series_title = item.get("SeriesName")
            series_id = item.get("SeriesId")  # 获取电视剧系列 ID
            # 修正：使用正确的键名来获取季度和集数
            season_number = item.get("ParentIndexNumber")
            episode_number = item.get("IndexNumber")

            if not all([series_title, season_number is not None, episode_number is not None]):
                logger.warning(f"Webhook: 忽略一个剧集，因为缺少系列标题、季度或集数信息。")
                return

            logger.info(f"Emby Webhook: 解析到剧集 - 标题: '{series_title}', 类型: Episode, 季: {season_number}, 集: {episode_number}")
            if event_type in ["item.add", "library.new"]:
                logger.info(f"Webhook: 收到剧集 '{series_title}' S{season_number:02d}E{episode_number:02d}' 的入库通知，将下载该集弹幕。")
            else:  # playback.start
                logger.info(f"Webhook: 收到剧集 '{series_title}' S{season_number:02d}E{episode_number:02d}' 的播放通知，将下载整部剧的弹幕。")

            # 尝试获取增强的元数据（安全模式，包含 Webhook 原始数据作为备用）
            try:
                enhanced_metadata = await enhance_webhook_metadata(item_id, series_id, payload)
                logger.info(f"增强元数据获取成功: {enhanced_metadata}")
            except Exception as e:
                logger.warning(f"增强元数据获取失败: {e}，使用基础元数据")
                enhanced_metadata = {
                    "tmdb_id": None, "imdb_id": None, "tvdb_id": None,
                    "douban_id": None, "bangumi_id": None
                }

            task_title = f"Webhook（emby）搜索: {series_title} - S{season_number:02d}E{episode_number:02d}"
            search_keyword = f"{series_title} S{season_number:02d}E{episode_number:02d}"
            media_type = "tv_series"
            anime_title = series_title
            
        elif item_type == "Movie":
            movie_title = item.get("Name")
            if not movie_title:
                logger.warning(f"Webhook: 忽略一个电影，因为缺少标题信息。")
                return

            logger.info(f"Emby Webhook: 解析到电影 - 标题: '{movie_title}', 类型: Movie")
            if event_type in ["item.add", "library.new"]:
                logger.info(f"Webhook: 收到电影 '{movie_title}' 的入库通知。")
            else:  # playback.start
                logger.info(f"Webhook: 收到电影 '{movie_title}' 的播放通知。")

            # 尝试获取增强的元数据（安全模式，包含 Webhook 原始数据作为备用）
            try:
                enhanced_metadata = await enhance_webhook_metadata(item_id, None, payload)
                logger.info(f"增强元数据获取成功: {enhanced_metadata}")
            except Exception as e:
                logger.warning(f"增强元数据获取失败: {e}，使用基础元数据")
                enhanced_metadata = {
                    "tmdb_id": None, "imdb_id": None, "tvdb_id": None,
                    "douban_id": None, "bangumi_id": None
                }

            task_title = f"Webhook（emby）搜索: {movie_title}"
            search_keyword = movie_title
            media_type = "movie"
            season_number = 1
            episode_number = 1 # 电影按单集处理
            anime_title = movie_title
        
        # 合并基础元数据和增强元数据，优先使用增强元数据
        final_tmdb_id = enhanced_metadata.get("tmdb_id") or basic_tmdb_id
        final_imdb_id = enhanced_metadata.get("imdb_id") or basic_imdb_id
        final_tvdb_id = enhanced_metadata.get("tvdb_id") or basic_tvdb_id
        final_douban_id = enhanced_metadata.get("douban_id") or basic_douban_id
        final_bangumi_id = enhanced_metadata.get("bangumi_id") or basic_bangumi_id

        # 新逻辑：总是触发全网搜索任务，并附带增强元数据ID
        unique_key = f"webhook-search-{anime_title}-S{season_number}-E{episode_number}"
        logger.info(f"Webhook: 准备为 '{anime_title}' 创建全网搜索任务，并附加增强元数据ID (TMDB: {final_tmdb_id}, IMDb: {final_imdb_id}, TVDB: {final_tvdb_id}, Douban: {final_douban_id}, Bangumi: {final_bangumi_id})。")

        # 使用新的、专门的 webhook 任务
        task_coro = lambda session, callback: webhook_search_and_dispatch_task(
            animeTitle=anime_title,
            mediaType=media_type,
            season=season_number,
            currentEpisodeIndex=episode_number,
            year=year,
            searchKeyword=search_keyword,
            doubanId=str(final_douban_id) if final_douban_id else None,
            tmdbId=str(final_tmdb_id) if final_tmdb_id else None,
            imdbId=str(final_imdb_id) if final_imdb_id else None,
            tvdbId=str(final_tvdb_id) if final_tvdb_id else None,
            bangumiId=str(final_bangumi_id) if final_bangumi_id else None,
            webhookSource='emby',
            eventType=event_type,  # 新增：传递事件类型
            progress_callback=callback,
            session=session,
            metadata_manager=self.metadata_manager,
            manager=self.scraper_manager, # type: ignore
            task_manager=self.task_manager,
            rate_limiter=self.rate_limiter
        )
        await self.task_manager.submit_task(task_coro, task_title, unique_key=unique_key)