"""YouTube Data API v3 client for video upload."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core.models import AppConfig


class YouTubeClient:
    """YouTube への動画アップロードを担当するクライアント。"""

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ]

    def __init__(self, config: AppConfig):
        self.config = config
        self.project_root = config.project_root
        self.client_secret_path = self.project_root / "client_secret.json"
        self.token_path = self.project_root / "token.json"

        publishing = getattr(config.yaml, "publishing", None)
        self.privacy_status = (
            publishing.privacy_status if publishing and publishing.privacy_status else "unlisted"
        )
        self.category_id = (
            publishing.category_id if publishing and publishing.category_id else "27"
        )

    def _get_credentials(self) -> Credentials:
        """OAuth2 認証情報を取得（token 再利用 + 必要時ブラウザ認証）。"""
        creds: Optional[Credentials] = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_path),
                self.SCOPES,
            )

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds

        if not self.client_secret_path.exists():
            raise FileNotFoundError(
                f"client_secret.json が見つかりません: {self.client_secret_path}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_path),
            self.SCOPES,
        )
        creds = flow.run_local_server(port=0)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _build_service(self):
        creds = self._get_credentials()
        return build("youtube", "v3", credentials=creds)

    def upload_video(
        self,
        file_path: Path,
        title: str,
        description: str,
        thumbnail_path: Optional[Path] = None,
    ) -> str:
        """動画を YouTube にアップロードして動画URLを返す。"""
        if not file_path.exists():
            raise FileNotFoundError(f"アップロード対象動画が見つかりません: {file_path}")

        youtube = self._build_service()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy_status,
            },
        }

        media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]

        if thumbnail_path and thumbnail_path.exists():
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path)),
            ).execute()

        return f"https://www.youtube.com/watch?v={video_id}"

    def add_video_to_playlist(self, video_id: str, playlist_id: str) -> None:
        """指定した動画を指定した再生リストへ追加する。"""
        youtube = self._build_service()

        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
