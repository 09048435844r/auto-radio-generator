"""ワークフローのチャプター整形ユーティリティ。

workflow.py から責務 #4（チャプター整形）を抽出したモジュール。
挙動は変更せず、以下のシンボルを提供する:

- _format_chapter_lines: ChapterMarker を YouTube 互換のタイムスタンプ行へ整形
- _build_metadata_chapter_block: metadata.txt 用のチャプターセクションを構築

後方互換のため workflow.py から再エクスポートされる。
"""
from core.interfaces import ChapterMarker


def _format_chapter_lines(chapters: list[ChapterMarker]) -> list[str]:
    """チャプター情報を YouTube 互換の `MM:SS タイトル` / `H:MM:SS タイトル` 形式に整形する。

    YouTube チャプター仕様への準拠:
      - 先頭チャプターは必ず `0:00` から開始（pre-roll 無音分を吸収）
      - 動画長が 1 時間を超える場合は `H:MM:SS`、それ以外は `MM:SS`
      - 同じタイトルが連続する場合は最初の1回のみ出力（重複防止）
      - 並び順は start_time_sec の昇順を保証

    Args:
        chapters: VoicevoxClient._build_chapters の出力（順序保証は呼び出し側に依存）

    Returns:
        `["0:00 はじめに", "3:45 トピックA", "7:32 まとめ"]` のような行リスト
    """
    if not chapters:
        return []

    # 並び順を保証（呼び出し側が既に並べていても安全側）
    sorted_chapters = sorted(chapters, key=lambda c: c.start_time_sec)

    # H:MM:SS が必要かどうかを最大タイムスタンプで決定
    max_seconds = int(max(c.start_time_sec for c in sorted_chapters))
    use_hours = max_seconds >= 3600

    chapter_lines: list[str] = []
    last_chapter_title = ""

    for idx, chapter in enumerate(sorted_chapters):
        # 同じタイトルが連続する場合は重複防止のためスキップ
        if chapter.title == last_chapter_title:
            continue

        # YouTube 仕様: 先頭は必ず 0:00。pre-roll 無音 (2秒) を吸収する。
        total_seconds = 0 if idx == 0 else max(0, int(chapter.start_time_sec))

        if use_hours:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            timestamp_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            timestamp_str = f"{minutes}:{seconds:02d}"

        chapter_lines.append(f"{timestamp_str} {chapter.title}")
        last_chapter_title = chapter.title

    return chapter_lines


def _build_metadata_chapter_block(chapters: list[ChapterMarker]) -> list[str]:
    """metadata.txt に挿入する YouTube チャプターセクションの行リストを構築する。

    このブロックは AI 生成のメタデータ本文のあと、VOICEVOX クレジット行の前に
    挿入され、視聴者向けに「概要欄へそのままコピー可能なチャプター一覧」を提供する。
    chapters が None / 空 / 全件サニタイズで弾かれた場合は空リストを返し、
    呼び出し側がスキップできるようにする。

    Args:
        chapters: ChapterMarker のリスト（VoicevoxClient._build_chapters 出力）

    Returns:
        metadata.txt の `lines` に extend する文字列リスト。空ならスキップ。
    """
    formatted = _format_chapter_lines(chapters)
    if not formatted:
        return []
    return [
        "【YouTubeチャプター】",
        "※ 以下をYouTubeの概要欄にそのまま貼り付けると、視聴者向けの目次になります",
        "",
        *formatted,
        "",
    ]
